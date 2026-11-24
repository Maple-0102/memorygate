"""Run one experimental condition over a list of tasks and record trajectories.

Week-1 conditions:
  no_memory     : schema + question
  evidence      : schema + question + the task's own official BIRD hint (reference group)
  raw_retrieval : + top-k past experiences from the same db (BM25), see memory.py
  shuffled      : + k random past experiences from the same db (placebo control)

Runs are resumable: items already in trajectories.jsonl are skipped.
"""
from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .data import Task, db_path, schema_ddl
from .grader import grade
from .llm import BudgetExceeded, UsageMeter
from .prompts import SYSTEM, build_prompt, extract_sql

HintFn = Callable[[Task], list[str]]

CONDITIONS: dict[str, HintFn] = {
    "no_memory": lambda t: [],
    "evidence": lambda t: [t.evidence],
}


def order_tasks(tasks: list[Task], order_seed: int) -> list[Task]:
    tasks = sorted(tasks, key=lambda t: t.qid)
    random.Random(order_seed).shuffle(tasks)
    return tasks


def _done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)["qid"] for l in path.read_text().splitlines() if l.strip()}


def run_condition(
    tasks: list[Task],
    condition: str,
    meter: UsageMeter,
    bird_dir: str | Path,
    out_dir: str | Path,
    exec_cfg: dict | None = None,
    hints_for: HintFn | None = None,
    meta: dict | None = None,
    retrieve: Callable[[Task], list] | None = None,
    workers: int = 1,
) -> dict:
    """`retrieve(task) -> list[Experience]` supplies memories; otherwise `hints_for` / CONDITIONS."""
    exec_cfg = exec_cfg or {}
    if retrieve is None:
        hints_for = hints_for or CONDITIONS[condition]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    traj_path = out_dir / "trajectories.jsonl"
    done = _done_ids(traj_path)
    label = "Hints" if condition == "evidence" else "Notes from similar past tasks on this database"

    # Memories are chosen serially and up front, so retrieval never races; only model calls run in parallel.
    jobs = []
    for t in tasks:
        if t.qid in done:
            continue
        if retrieve is not None:
            mems = retrieve(t)
            hints, memory_ids = [m.render() for m in mems], [m.qid for m in mems]
        else:
            hints, memory_ids = hints_for(t), []
        jobs.append((t, hints, memory_ids))

    lock = threading.Lock()

    def solve(job):
        t, hints, memory_ids = job
        dbp = db_path(bird_dir, t.db_id)
        prompt = build_prompt(schema_ddl(str(dbp)), t.question, hints, label)
        comp = meter.generate(prompt, SYSTEM, tag=f"{condition}:solve")
        sql = extract_sql(comp.text)
        g = grade(dbp, sql, t.gold_sql, exec_cfg.get("timeout_s", 30), exec_cfg.get("max_rows", 100_000))
        rec = {
            "qid": t.qid,
            "db_id": t.db_id,
            "difficulty": t.difficulty,
            "condition": condition,
            "hints": hints,
            "memory_ids": memory_ids,
            "pred_sql": sql,
            "raw_output": comp.text,
            "correct": g.correct,
            "strict": g.strict,
            "pred_error": g.pred_error,
            "gold_error": g.gold_error,
            "input_tokens": comp.input_tokens,
            "output_tokens": comp.output_tokens,
            "thinking_tokens": comp.thinking_tokens,
            "latency_s": round(comp.latency_s, 3),
            "ts": time.time(),
        }
        with lock, open(traj_path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    stopped = None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(solve, j) for j in jobs]
        for fut in as_completed(futures):
            if fut.cancelled():
                continue
            try:
                fut.result()
            except BudgetExceeded as e:
                stopped = str(e)
                for f in futures:
                    f.cancel()
    summary = summarize(traj_path) if traj_path.exists() else {"n": 0}
    summary.update({"condition": condition, "usage_this_invocation": meter.summary(), "stopped": stopped, **(meta or {})})
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return summary


def load_traj(path: str | Path) -> list[dict]:
    p = Path(path)
    if p.is_dir():
        p = p / "trajectories.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def summarize(path: str | Path) -> dict:
    recs = load_traj(path)
    graded = [r for r in recs if not r["gold_error"]]
    per_db: dict[str, list[bool]] = defaultdict(list)
    for r in graded:
        per_db[r["db_id"]].append(r["correct"])
    acc = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {
        "n": len(recs),
        "n_graded": len(graded),
        "n_gold_error": len(recs) - len(graded),
        "accuracy": acc([r["correct"] for r in graded]),
        "pred_error_rate": acc([bool(r["pred_error"]) for r in graded]),
        "per_db": {db: {"n": len(v), "accuracy": acc(v)} for db, v in sorted(per_db.items())},
    }


def paired(a: str | Path, b: str | Path) -> dict:
    """Item-level comparison of run B against run A on their shared, gradable items."""
    ra = {r["qid"]: r for r in load_traj(a) if not r["gold_error"]}
    rb = {r["qid"]: r for r in load_traj(b) if not r["gold_error"]}
    shared = sorted(ra.keys() & rb.keys())
    fixed = [q for q in shared if not ra[q]["correct"] and rb[q]["correct"]]
    broken = [q for q in shared if ra[q]["correct"] and not rb[q]["correct"]]
    n = len(shared)
    return {
        "n_shared": n,
        "acc_a": round(sum(ra[q]["correct"] for q in shared) / n, 4) if n else None,
        "acc_b": round(sum(rb[q]["correct"] for q in shared) / n, 4) if n else None,
        "fixed": len(fixed),
        "broken": len(broken),
        "flip_rate": round((len(fixed) + len(broken)) / n, 4) if n else None,
        "fixed_ids": fixed,
        "broken_ids": broken,
    }
