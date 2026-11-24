"""Round loop for one experimental group.

Each round:  solve a batch of learning tasks with the current memory  →  update memory
             (raw: append experiences; consolidate: distill + consolidate into a candidate;
              gate_*: the candidate must pass the gate on val, else the old version stays)
             →  every `eval_every` rounds, evaluate the current memory on the evaluation set.

Groups: no_memory | raw | consolidate | gate_accept | gate_reject  (plus the evidence reference group,
which is round-independent and run with `memorygate run --condition evidence`).

Development mode (default): the evaluation set is a fixed 30% of the learn split per database
("dev_eval"), and only the other 70% is streamed as learning tasks. The sealed test split is used
only in final mode, after the design is frozen.

Every round writes runs/<name>/round_XX/ with learn/, eval/, gate_*/ trajectories, memory.json,
report.md and done.json, so an interrupted run resumes from the last finished round.
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from .consolidate import consolidate_round
from .data import Task, load_bird
from .gate import decide
from .llm import UsageMeter
from .memory import Experience, ExperienceBank
from .memstore import MemoryStore, diff, fit_budget
from .runner import load_traj, paired, run_condition, summarize
from .splits import load_split

GROUPS = ("no_memory", "raw", "consolidate", "gate_accept", "gate_reject")


def dev_streams(cfg: dict, final: bool = False) -> tuple[list[Task], list[Task], list[Task], dict[str, Task]]:
    """(learning stream, evaluation set, val set, all tasks by id)."""
    d, rc = cfg["data"], cfg["rounds"]
    by_id = {t.qid: t for t in load_bird(d["bird_dir"])}
    learn = [by_id[i] for i in load_split("learn", d["seed"], d["split_dir"], d["sealed_dir"])]
    val = [by_id[i] for i in load_split("val", d["seed"], d["split_dir"], d["sealed_dir"])]
    if final:
        test = [by_id[i] for i in load_split("test", d["seed"], d["split_dir"], d["sealed_dir"], unseal=True)]
        return learn, test, val, by_id
    per_db: dict[str, list[Task]] = {}
    for t in learn:
        per_db.setdefault(t.db_id, []).append(t)
    stream, ev = [], []
    for db in sorted(per_db):
        ts = sorted(per_db[db], key=lambda t: t.qid)
        random.Random(f"{rc['dev_eval_seed']}:{db}").shuffle(ts)
        n = round(len(ts) * rc["dev_eval_frac"])
        ev += ts[:n]
        stream += ts[n:]
    return stream, sorted(ev, key=lambda t: t.qid), val, by_id


def chunk(tasks: list[Task], order_seed: int, n_rounds: int) -> list[list[Task]]:
    ts = sorted(tasks, key=lambda t: t.qid)
    random.Random(order_seed).shuffle(ts)
    size = -(-len(ts) // n_rounds)
    return [ts[i : i + size] for i in range(0, len(ts), size)]


class RawMemory:
    """Raw-experience bank for the round loop."""

    def __init__(self, exps: list[Experience] | None = None):
        self.exps = list(exps or [])
        self._bank = ExperienceBank(self.exps)

    def add(self, trajs: list[dict], by_id: dict[str, Task]) -> None:
        for r in trajs:
            if r["gold_error"]:
                continue
            t = by_id[r["qid"]]
            self.exps.append(Experience(t.qid, t.db_id, t.question, t.gold_sql, r["pred_sql"], r["pred_error"], r["correct"]))
        self._bank = ExperienceBank(self.exps)

    def retrieve(self, task: Task, k: int, budget: int):
        return fit_budget(self._bank.retrieve(task, k * 3), k, budget)

    def to_json(self) -> dict:
        return {"experiences": [e.__dict__ for e in self.exps]}

    @classmethod
    def from_json(cls, d: dict) -> "RawMemory":
        return cls([Experience(**e) for e in d["experiences"]])


def _save(path: Path, mem) -> None:
    path.write_text(json.dumps(mem.to_json(), indent=1, ensure_ascii=False))


def run_group(cfg: dict, group: str, meter: UsageMeter, out: Path, order_seed: int, max_rounds: int | None = None,
              workers: int = 8, final: bool = False) -> list[dict]:
    if group not in GROUPS:
        raise ValueError(group)
    rc, bird = cfg["rounds"], cfg["data"]["bird_dir"]
    stream, eval_set, val, by_id = dev_streams(cfg, final)
    batches = chunk(stream, order_seed, rc["n_rounds"])
    k, budget, every = rc["k"], rc["char_budget"], rc["eval_every"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({"group": group, "order_seed": order_seed, "final": final,
                                                 "rounds": rc, "model": cfg["model"]["name"],
                                                 "n_stream": len(stream), "n_eval": len(eval_set), "n_val": len(val)}, indent=1))
    is_cons = group in ("consolidate", "gate_accept", "gate_reject")
    mem = MemoryStore() if is_cons else RawMemory()
    history = []

    for r, batch in enumerate(batches):
        if max_rounds is not None and r >= max_rounds:
            break
        rd = out / f"round_{r:02d}"
        if (rd / "done.json").exists():
            d = json.loads((rd / "memory.json").read_text())
            mem = MemoryStore.from_json(d) if is_cons else RawMemory.from_json(d)
            history.append(json.loads((rd / "done.json").read_text()))
            continue
        rd.mkdir(parents=True, exist_ok=True)
        if is_cons:  # an interrupted round re-runs consolidation, so results that depend on the candidate are stale
            for sub in ("gate_current", "gate_candidate", "eval"):
                shutil.rmtree(rd / sub, ignore_errors=True)
        rec: dict = {"round": r, "group": group, "n_batch": len(batch)}
        before = mem

        def retr(m):
            return None if group == "no_memory" else (lambda t: m.retrieve(t, k, budget))

        # 1. solve this round's learning batch with the current memory
        if group != "no_memory":
            s = run_condition(batch, group, meter, bird, rd / "learn", retrieve=retr(mem), workers=workers)
            rec["learn_acc"] = s["accuracy"]
            trajs = load_traj(rd / "learn")

            # 2. update memory
            if group == "raw":
                mem = RawMemory(mem.exps)
                mem.add(trajs, by_id)
            else:
                for t in trajs:
                    mem.record_outcome(t.get("memory_ids", []), t["correct"])
                cand, clog = consolidate_round(meter, mem, bird, trajs, by_id, r, rc, workers)
                rec["consolidation"] = clog
                _save(rd / "candidate.json", cand)          # kept for independent post-hoc labelling
                _save(rd / "before.json", mem)              # the version the candidate is compared against
                rec["diff"] = diff(mem, cand)
                if group == "consolidate":
                    mem = cand
                else:
                    policy = "default_accept" if group == "gate_accept" else "default_reject"
                    run_condition(val, "gate_current", meter, bird, rd / "gate_current", retrieve=retr(mem), workers=workers)
                    run_condition(val, "gate_candidate", meter, bird, rd / "gate_candidate", retrieve=retr(cand), workers=workers)
                    p = paired(rd / "gate_current", rd / "gate_candidate")
                    g = decide(p["fixed"], p["broken"], p["n_shared"], policy, rc["gate_z"])
                    rec["gate"] = g.to_dict() | {"acc_current": p["acc_a"], "acc_candidate": p["acc_b"]}
                    if g.accept:
                        mem = cand
                    else:  # whole-version rollback; keep the rejected entries on record as quarantined
                        kept = mem.copy()
                        for a in rec["diff"]["added"]:
                            e = cand.entries[a["id"]]
                            e.status = "quarantined"
                            kept.entries[e.id] = e
                        kept.next_id = cand.next_id
                        mem = kept
        rec["memory_size"] = len(mem.active()) if is_cons else len(getattr(mem, "exps", []))

        # 3. evaluate
        last = r == len(batches) - 1 or (max_rounds is not None and r == max_rounds - 1)
        if (r + 1) % every == 0 or last:
            s = run_condition(eval_set, group, meter, bird, rd / "eval", retrieve=retr(mem), workers=workers)
            rec["eval_acc"] = s["accuracy"]
            rec["eval_n"] = s["n_graded"]
        rec["usd_so_far"] = round(meter.usd, 4)
        _save(rd / "memory.json", mem)
        (rd / "report.md").write_text(round_report(rec, before, mem, is_cons))
        (rd / "done.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        history.append(rec)
    return history


def round_report(rec: dict, before, after, is_cons: bool) -> str:
    L = [f"# Round {rec['round']} · {rec['group']}\n"]
    for k_, label in (("learn_acc", "learning batch accuracy"), ("eval_acc", "evaluation accuracy"),
                      ("memory_size", "active memory entries"), ("usd_so_far", "cost so far (USD)")):
        if k_ in rec:
            L.append(f"- {label}: {rec[k_]}")
    if "gate" in rec:
        g = rec["gate"]
        L.append(f"\n## Gate ({g['policy']}): {'ACCEPTED' if g['accept'] else 'REJECTED → rolled back'}\n")
        L.append(f"- val accuracy current {g['acc_current']} → candidate {g['acc_candidate']}; fixed {g['fixed']}, "
                 f"broken {g['broken']}, z = {g['z']} ({g['effect']})")
    if "diff" in rec:
        d = rec["diff"]
        L.append(f"\n## Memory changes (candidate): {d['n_active_before']} → {d['n_active_after']} active\n")
        for a in d["added"]:
            L.append(f"- **+ {a['id']}** `{a['scope']}` {a['text']}")
        for m in d["merges"]:
            L.append(f"- merged {', '.join(m['from'])} → {m['id']}")
        for x in d["removed"]:
            L.append(f"- **− {x['id']}** ({x['status']}) {x['text']}")
    if is_cons:
        q = [e for e in after.entries.values() if e.status == "quarantined" and e.created_round == rec["round"]]
        if q:
            L.append("\n## Quarantined this round\n")
            L += [f"- {e.id} `{e.scope}` {e.text}" for e in q]
    return "\n".join(L) + "\n"
