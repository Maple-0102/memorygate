"""Post-hoc labelling of memory updates, and the round-experiment summary.

For every consolidation update, evaluate the version before and the candidate on the evaluation set,
which the gate never sees, and label the update with the same paired test the gate uses:
  improved (beneficial) / worse (harmful) / unclear (within noise).
Comparing labels with the gate's own decisions gives, update by update:
  false accept  = a harmful update the gate let through
  false reject  = a beneficial update the gate blocked
Evaluations are cached by memory content, so an unchanged version is evaluated once.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .gate import decide
from .llm import UsageMeter
from .memstore import MemoryStore
from .rounds import dev_streams
from .runner import load_traj, paired, run_condition


def _key(store: MemoryStore) -> str:
    items = sorted((e.id, e.scope, e.text) for e in store.active())
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def _pairs(run: Path) -> list[tuple[int, MemoryStore, MemoryStore, dict]]:
    """(round, before, candidate, done) for each round with an update."""
    out = []
    prev = MemoryStore()
    for rd in sorted(run.glob("round_*")):
        done_p = rd / "done.json"
        if not done_p.exists():
            break
        done = json.loads(done_p.read_text())
        if (rd / "candidate.json").exists():
            before, cand = MemoryStore.load(rd / "before.json"), MemoryStore.load(rd / "candidate.json")
        else:  # ungated consolidate group: every candidate took effect
            before, cand = prev, MemoryStore.load(rd / "memory.json")
        out.append((done["round"], before, cand, done))
        prev = MemoryStore.load(rd / "memory.json")
    return out


def label_run(cfg: dict, run: Path, meter: UsageMeter, workers: int = 8) -> list[dict]:
    rc, bird = cfg["rounds"], cfg["data"]["bird_dir"]
    _, eval_set, _, _ = dev_streams(cfg)
    k, budget = rc["k"], rc["char_budget"]
    cache = run / "label_cache"
    rows = []
    for r, before, cand, done in _pairs(run):
        dirs = []
        for store in (before, cand):
            d = cache / _key(store)
            run_condition(eval_set, "label", meter, bird, d, retrieve=lambda t, m=store: m.retrieve(t, k, budget),
                          workers=workers)
            dirs.append(d)
        p = paired(dirs[0], dirs[1])
        lab = decide(p["fixed"], p["broken"], p["n_shared"], "default_accept", rc["gate_z"])
        gate = done.get("gate")
        rows.append({
            "round": r, "label": lab.effect, "eval_before": p["acc_a"], "eval_candidate": p["acc_b"],
            "fixed": p["fixed"], "broken": p["broken"], "z": lab.z,
            "accepted": gate["accept"] if gate else True, "gate_z": gate["z"] if gate else None,
            "n_added": len(done.get("diff", {}).get("added", [])), "n_removed": len(done.get("diff", {}).get("removed", [])),
        })
    (run / "labels.json").write_text(json.dumps(rows, indent=1))
    return rows


def gate_scorecard(rows: list[dict]) -> dict:
    harmful = [r for r in rows if r["label"] == "worse"]
    helpful = [r for r in rows if r["label"] == "improved"]
    return {
        "updates": len(rows),
        "harmful": len(harmful), "harmful_accepted": sum(r["accepted"] for r in harmful),
        "beneficial": len(helpful), "beneficial_rejected": sum(not r["accepted"] for r in helpful),
        "unclear": len(rows) - len(harmful) - len(helpful),
        "unclear_accepted": sum(r["accepted"] for r in rows if r["label"] == "unclear"),
    }


def rounds_summary(runs_dir: str | Path, out_path: str | Path) -> str:
    R = Path(runs_dir)
    groups = ["no_memory", "raw", "consolidate", "gate_accept", "gate_reject"]
    curves: dict[str, dict[int, list[float]]] = {g: {} for g in groups}
    orders = sorted({p.name.split("_")[0] for p in R.glob("o*_*") if p.is_dir()})
    for o in orders:
        for g in groups:
            for done in sorted((R / f"{o}_{g}").glob("round_*/done.json")):
                d = json.loads(done.read_text())
                if d.get("eval_acc") is not None:
                    curves[g].setdefault(d["round"], []).append(d["eval_acc"])
    rounds = sorted({r for c in curves.values() for r in c})
    L = ["# Round experiment: evaluation accuracy by round\n",
         f"Orders found: {', '.join(orders)}. Cells: mean over orders (min–max, n orders).\n",
         "| round | " + " | ".join(groups) + " |", "|---" * (len(groups) + 1) + "|"]
    for r in rounds:
        cells = []
        for g in groups:
            xs = curves[g].get(r, [])
            cells.append(f"{sum(xs) / len(xs):.3f} ({min(xs):.3f}–{max(xs):.3f}, {len(xs)})" if xs else "")
        L.append(f"| {r} | " + " | ".join(cells) + " |")

    L.append("\n## Gate decisions and independent labels\n")
    L.append("| run | updates | harmful (accepted) | beneficial (rejected) | unclear (accepted) | accepted / total |")
    L.append("|---|---|---|---|---|---|")
    for run in sorted(R.glob("o*_*")):
        lp = run / "labels.json"
        if not lp.exists():
            continue
        rows = json.loads(lp.read_text())
        s = gate_scorecard(rows)
        L.append(f"| {run.name} | {s['updates']} | {s['harmful']} ({s['harmful_accepted']}) | "
                 f"{s['beneficial']} ({s['beneficial_rejected']}) | {s['unclear']} ({s['unclear_accepted']}) | "
                 f"{sum(r['accepted'] for r in rows)} / {len(rows)} |")
    text = "\n".join(L) + "\n"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(text)
    return text


FINAL_PAIRS = [("no_memory", "raw"), ("no_memory", "consolidate"), ("no_memory", "gate_accept"),
               ("no_memory", "gate_reject"), ("consolidate", "raw"), ("consolidate", "gate_accept"),
               ("consolidate", "gate_reject")]


def final_summary(runs_dir: str | Path) -> str:
    """Pre-registered final comparison on the test split, at the last evaluated round.

    The unit is the question: for each test question, correctness is averaged over the task orders
    found, and B - A is tested with a paired z on those per-question differences (two-sided, 1.96).
    """
    from math import sqrt
    R = Path(runs_dir)
    orders = sorted({p.name.split("_")[0] for p in R.glob("o*_*") if p.is_dir()})

    def last_eval(o, g):
        ds = sorted((R / f"{o}_{g}").glob("round_*/eval"))
        return {r["qid"]: r["correct"] for r in load_traj(ds[-1]) if not r["gold_error"]} if ds else None

    res = {g: [e for o in orders if (e := last_eval(o, g)) is not None] for g in
           ("no_memory", "raw", "consolidate", "gate_accept", "gate_reject")}
    L = ["# Final comparison on the test split (pre-registered)\n",
         f"Orders: {', '.join(orders)}. Last evaluated round. Unit = test question, correctness averaged over orders.\n",
         "| B vs A | acc A | acc B | Δ (B − A) | z | verdict (|z| > 1.96) |", "|---|---|---|---|---|---|"]
    for a, b in FINAL_PAIRS:
        ea, eb = res[a], res[b]
        if not ea or not eb:
            continue
        qs = sorted(set.intersection(*(set(e) for e in ea + eb)))
        ma = [sum(e[q] for e in ea) / len(ea) for q in qs]
        mb = [sum(e[q] for e in eb) / len(eb) for q in qs]
        d = [y - x for x, y in zip(ma, mb)]
        n = len(d)
        md = sum(d) / n
        sd = sqrt(sum((x - md) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
        z = md / (sd / sqrt(n)) if sd > 0 else 0.0
        verdict = "B better" if z > 1.96 else "B worse" if z < -1.96 else "no clear difference"
        L.append(f"| {b} vs {a} | {sum(ma) / n:.3f} | {sum(mb) / n:.3f} | {md:+.3f} | {z:+.2f} | {verdict} |")
    return "\n".join(L) + "\n"
