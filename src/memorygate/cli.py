"""Command line: split / run / summary / compare."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from .config import load_config
from .data import load_bird
from .llm import make_client
from .memory import ExperienceBank
from .runner import CONDITIONS, load_traj, order_tasks, paired, run_condition, summarize
from .splits import load_split, make_split, write_split


def cmd_split(cfg: dict, args) -> None:
    d = cfg["data"]
    src = Path(d["bird_dir"]) / "dev.json"
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    tasks = load_bird(d["bird_dir"])
    split = make_split(tasks, d["seed"], d["ratios"])
    path = write_split(split, d["seed"], d["split_dir"], d["sealed_dir"], sha)
    print(f"wrote {path}: learn={len(split['learn'])} val={len(split['val'])} test={len(split['test'])} (sealed)")


MEMORY_CONDITIONS = ("raw_retrieval", "shuffled")


def build_bank(by_id: dict, d: dict, args) -> ExperienceBank:
    """Experience bank from a public split, optionally subsampled (to test reproducibility across batches)
    and annotated with the agent's own attempts from an earlier run on that split."""
    ids = []
    for name in args.bank_split.split(","):
        ids += load_split(name, d["seed"], d["split_dir"], d["sealed_dir"])
    if args.bank_frac < 1.0:
        rng = random.Random(args.bank_seed)
        ids = sorted(rng.sample(sorted(ids), round(len(ids) * args.bank_frac)))
    attempts = {r["qid"]: r for r in load_traj(Path("runs") / args.bank_run)} if args.bank_run else None
    return ExperienceBank.from_tasks([by_id[i] for i in ids], attempts)


def cmd_run(cfg: dict, args) -> None:
    d = cfg["data"]
    by_id = {t.qid: t for t in load_bird(d["bird_dir"])}
    ids: list[str] = []
    for name in args.split.split(","):
        ids += load_split(name, d["seed"], d["split_dir"], d["sealed_dir"])
    tasks = [by_id[i] for i in ids]
    if args.dbs:
        keep = set(args.dbs.split(","))
        tasks = [t for t in tasks if t.db_id in keep]
    tasks = order_tasks(tasks, args.order_seed)
    if args.limit:
        tasks = tasks[: args.limit]
    out = Path("runs") / args.name
    meta = {"split": args.split, "order_seed": args.order_seed, "limit": args.limit, "dbs": args.dbs,
            "model": cfg["model"]["name"], "provider": cfg["model"]["provider"], "config": cfg["_path"]}
    retrieve = None
    if args.condition in MEMORY_CONDITIONS:
        bank = build_bank(by_id, d, args)
        overlap = bank.items.keys() & {t.qid for t in tasks}
        if overlap:
            raise SystemExit(f"{len(overlap)} eval tasks are also in the experience bank; evaluate on a different split")
        k = args.k
        if args.condition == "raw_retrieval":
            retrieve = lambda t: bank.retrieve(t, k)
        else:
            retrieve = lambda t: bank.random_same_db(t, k, args.bank_seed)
        meta.update({"bank_split": args.bank_split, "bank_run": args.bank_run, "bank_frac": args.bank_frac,
                     "bank_seed": args.bank_seed, "bank_size": len(bank), "k": k})
    meter = make_client(cfg, log_path=out / "usage.jsonl")
    s = run_condition(tasks, args.condition, meter, d["bird_dir"], out, cfg.get("exec"), meta=meta, retrieve=retrieve,
                      workers=args.workers)
    print(json.dumps({k: v for k, v in s.items() if k != "per_db"}, indent=1))


def inspect_md(a: Path, b: Path, broken: bool = False) -> str:
    ra = {r["qid"]: r for r in load_traj(a)}
    rb = {r["qid"]: r for r in load_traj(b)}
    res = paired(a, b)
    ids = res["broken_ids"] if broken else res["fixed_ids"]
    out = [f"# {'Broken' if broken else 'Fixed'} by {b.name} vs {a.name}: {len(ids)} of {res['n_shared']}\n"]
    for q in ids:
        x, y = ra[q], rb[q]
        out.append(f"## {q} · {y['db_id']}\n")
        out.append(f"- **{a.name}** SQL: `{x['pred_sql']}`" + (f" (error: {x['pred_error']})" if x["pred_error"] else ""))
        out.append(f"- **{b.name}** SQL: `{y['pred_sql']}`")
        for h in y.get("hints", []):
            out.append("  - memory: " + h.replace("\n", " "))
        out.append("- Which memory supplied the field, table or formula? → _fill in_\n")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="memorygate")
    p.add_argument("-c", "--config", default="configs/week1.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split", help="create the frozen learn/val/test split (test is sealed)")
    r = sub.add_parser("run", help="run one condition")
    r.add_argument("--condition", choices=sorted(CONDITIONS) + list(MEMORY_CONDITIONS), required=True)
    r.add_argument("--split", default="learn,val", help="comma list of learn,val (test is sealed)")
    r.add_argument("--bank-split", default="learn", help="split whose tasks form the experience bank")
    r.add_argument("--bank-run", default="", help="earlier run on the bank split, to include the agent's own attempts")
    r.add_argument("--bank-frac", type=float, default=1.0, help="subsample the bank (reproducibility check)")
    r.add_argument("--bank-seed", type=int, default=0)
    r.add_argument("--k", type=int, default=3, help="experiences per question")
    r.add_argument("--workers", type=int, default=8, help="parallel model calls")
    r.add_argument("--dbs", default="", help="comma list of db_ids to keep")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--order-seed", type=int, default=0)
    r.add_argument("--name", required=True, help="run folder under runs/")
    s = sub.add_parser("summary")
    s.add_argument("run")
    c = sub.add_parser("compare", help="paired fixed/broken between two runs")
    c.add_argument("a")
    c.add_argument("b")
    i = sub.add_parser("inspect", help="markdown of items B fixed over A, with the memories B saw (for attribution)")
    i.add_argument("a")
    i.add_argument("b")
    i.add_argument("--broken", action="store_true", help="show items B broke instead")
    g = sub.add_parser("rounds", help="round-based run for one group")
    g.add_argument("--group", required=True, choices=["no_memory", "raw", "consolidate", "gate_accept", "gate_reject"])
    g.add_argument("--order-seed", type=int, default=0)
    g.add_argument("--name", required=True)
    g.add_argument("--max-rounds", type=int, default=None, help="stop early (pilot)")
    g.add_argument("--workers", type=int, default=8)
    g.add_argument("--final", action="store_true", help="final mode: stream all of learn, evaluate on the sealed test split")
    g.add_argument("--eval-every", type=int, default=None, help="override rounds.eval_every")
    lb = sub.add_parser("label", help="independent post-hoc labels for each memory update of a run")
    lb.add_argument("--run", required=True)
    lb.add_argument("--workers", type=int, default=8)
    hj = sub.add_parser("inject", help="harm injection: replay a gated run's updates with corrupted candidates")
    hj.add_argument("--run", required=True)
    hj.add_argument("--frac", type=float, required=True, help="fraction of active entries to corrupt")
    hj.add_argument("--workers", type=int, default=4)
    hr = sub.add_parser("inject-report", help="summary of harm injection to reports/injection.md")
    hr.add_argument("--out", default="reports/injection.md")
    sr = sub.add_parser("rounds-report", help="summary of round runs to reports/rounds.md")
    sr.add_argument("--out", default="reports/rounds.md")
    sr.add_argument("--runs", default="runs")
    fr = sub.add_parser("final-report", help="pre-registered final comparison to reports/final.md")
    fr.add_argument("--runs", default="runs/final")
    fr.add_argument("--out", default="reports/final.md")
    w = sub.add_parser("report", help="week-1 report to reports/week1.md")
    w.add_argument("--out", default="reports/week1.md")
    args = p.parse_args(argv)

    if args.cmd == "rounds":
        from .rounds import run_group
        cfg = load_config(args.config)
        cfg["budget"] = {"max_calls": None, "max_usd": cfg["rounds"]["max_usd_per_group"]}
        if args.eval_every:
            cfg["rounds"]["eval_every"] = args.eval_every
        out = Path("runs") / args.name
        meter = make_client(cfg, log_path=out / "usage.jsonl")
        hist = run_group(cfg, args.group, meter, out, args.order_seed, args.max_rounds, args.workers, final=args.final)
        for h in hist:
            print(json.dumps({k: h.get(k) for k in ("round", "learn_acc", "eval_acc", "memory_size", "usd_so_far")}
                             | ({"gate": h["gate"]["accept"], "z": h["gate"]["z"]} if "gate" in h else {})))
        print("this invocation:", json.dumps(meter.summary()))
        return
    if args.cmd == "label":
        from .posthoc import gate_scorecard, label_run
        cfg = load_config(args.config)
        cfg["budget"] = {"max_calls": None, "max_usd": cfg["rounds"]["max_usd_per_group"]}
        run = Path("runs") / args.run
        meter = make_client(cfg, log_path=run / "label_usage.jsonl")
        rows = label_run(cfg, run, meter, args.workers)
        for r in rows:
            print(json.dumps(r))
        print(json.dumps(gate_scorecard(rows)), "| cost:", json.dumps(meter.summary()))
        return
    if args.cmd == "inject":
        from .harm import inject_run
        cfg = load_config(args.config)
        cfg["budget"] = {"max_calls": None, "max_usd": cfg["rounds"]["max_usd_per_group"]}
        run = Path("runs") / args.run
        meter = make_client(cfg, log_path=run / "inject_usage.jsonl")
        for r in inject_run(cfg, run, args.frac, meter, args.workers):
            print(json.dumps(r))
        print("cost:", json.dumps(meter.summary()))
        return
    if args.cmd == "inject-report":
        from .harm import injection_summary
        text = injection_summary("runs")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(text)
        return
    if args.cmd == "rounds-report":
        from .posthoc import rounds_summary
        print(rounds_summary(args.runs, args.out))
        return
    if args.cmd == "final-report":
        from .posthoc import final_summary
        text = final_summary(args.runs)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(text)
        return
    if args.cmd == "report":
        from .analysis import week1_report
        cfg = load_config(args.config)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        print(week1_report("runs", cfg["data"]["bird_dir"], args.out))
        return

    if args.cmd == "inspect":
        print(inspect_md(Path("runs") / args.a, Path("runs") / args.b, args.broken))
        return

    if args.cmd == "summary":
        print(json.dumps(summarize(Path("runs") / args.run / "trajectories.jsonl"), indent=1))
        return
    if args.cmd == "compare":
        res = paired(Path("runs") / args.a, Path("runs") / args.b)
        print(json.dumps({k: v for k, v in res.items() if not k.endswith("_ids")}, indent=1))
        return
    cfg = load_config(args.config)
    {"split": cmd_split, "run": cmd_run}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
