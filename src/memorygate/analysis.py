"""Week-1 analysis: noise floor, headroom, retrieval gain vs placebo, reproducibility, attribution, cost."""
from __future__ import annotations

import json
import re
from math import comb
from pathlib import Path

from .data import load_bird
from .runner import load_traj, paired

SQL_WORDS = {
    "select", "from", "where", "and", "or", "not", "as", "on", "join", "inner", "left", "right", "outer", "group",
    "by", "order", "having", "limit", "desc", "asc", "count", "sum", "avg", "min", "max", "distinct", "case", "when",
    "then", "else", "end", "cast", "real", "integer", "in", "is", "null", "like", "between", "with", "union", "t1",
    "t2", "t3", "t4", "iif", "strftime", "substr", "length", "round", "abs", "exists", "all", "text", "offset",
}
_TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|'[^']*'|\d+(?:\.\d+)?")


def sql_tokens(sql: str | None) -> set[str]:
    if not sql:
        return set()
    return {t.lower().strip("`\"") for t in _TOK.findall(sql) if t.lower() not in SQL_WORDS}


def mcnemar_p(fixed: int, broken: int) -> float:
    """Exact two-sided McNemar (binomial on discordant pairs)."""
    n = fixed + broken
    if n == 0:
        return 1.0
    k = min(fixed, broken)
    p = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def restrict(run: str, ids: set[str], runs_dir: Path) -> Path:
    """Write the subset of a run's trajectories to a temp dir so paired() can compare like with like."""
    src = load_traj(runs_dir / run)
    out = runs_dir / "_subsets" / f"{run}__{len(ids)}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "trajectories.jsonl").write_text("".join(json.dumps(r) + "\n" for r in src if r["qid"] in ids))
    return out


def attribute(base: Path, mem: Path, bird_dir: str) -> list[dict]:
    """For items the memory run fixed: did a retrieved experience supply an identifier/constant that the
    gold SQL needs, that the baseline missed, and that the memory run then used? A proxy, to be checked by hand."""
    gold = {t.qid: t for t in load_bird(bird_dir)}
    ra = {r["qid"]: r for r in load_traj(base)}
    rb = {r["qid"]: r for r in load_traj(mem)}
    out = []
    for q in paired(base, mem)["fixed_ids"]:
        need = sql_tokens(gold[q].gold_sql) - sql_tokens(ra[q]["pred_sql"])
        mem_toks = set()
        for h in rb[q].get("hints", []):
            m = re.search(r"Correct SQL: (.*)$", h, re.S)
            mem_toks |= sql_tokens(m.group(1) if m else h)
        supplied = sorted(need & mem_toks & sql_tokens(rb[q]["pred_sql"]))
        out.append({"qid": q, "db_id": rb[q]["db_id"], "supplied": supplied, "memory_ids": rb[q].get("memory_ids", [])})
    return out


def week1_report(runs_dir: str | Path, bird_dir: str, out_path: str | Path) -> str:
    R = Path(runs_dir)
    have = lambda n: (R / n / "trajectories.jsonl").exists()
    L: list[str] = ["# Week-1 feasibility results\n"]

    def row(name, a, b, note=""):
        p = paired(a, b)
        pv = mcnemar_p(p["fixed"], p["broken"])
        L.append(f"| {name} | {p['n_shared']} | {p['acc_a']:.3f} | {p['acc_b']:.3f} | {p['acc_b'] - p['acc_a']:+.3f} | "
                 f"{p['fixed']} | {p['broken']} | {pv:.3g} | {note} |")
        return p

    L.append("| comparison (A → B) | n | acc A | acc B | Δ | fixed | broken | McNemar p | note |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    if have("nomem_r1") and have("nomem_r2"):
        row("no-memory run 1 → run 2", R / "nomem_r1", R / "nomem_r2", "noise floor (same prompt, temp 0)")
    if have("nomem_r1") and have("evid_r1"):
        row("no-memory → official hints", R / "nomem_r1", R / "evid_r1", "headroom: is there something to learn?")
    val_ids = {r["qid"] for r in load_traj(R / "raw_k3")} if have("raw_k3") else set()
    if val_ids:
        base_val = restrict("nomem_r1", val_ids, R)
        row("no-memory → raw retrieval (val)", base_val, R / "raw_k3", "does past experience help new tasks?")
        if have("evid_r1"):
            row("no-memory → official hints (val)", base_val, restrict("evid_r1", val_ids, R), "headroom on the same items")
        if have("nomem_r2"):
            row("no-memory r1 → r2 (val)", base_val, restrict("nomem_r2", val_ids, R), "noise on the same items")
        if have("shuf_k3"):
            row("no-memory → shuffled same-db (val)", base_val, R / "shuf_k3", "placebo")
            row("shuffled → raw retrieval (val)", R / "shuf_k3", R / "raw_k3", "relevance beyond placebo")
        for h in ("raw_k3_halfA", "raw_k3_halfB"):
            if have(h):
                row(f"no-memory → {h} (val)", base_val, R / h, "half of the bank")
        if have("raw_k3_halfA") and have("raw_k3_halfB"):
            fa = set(paired(base_val, R / "raw_k3_halfA")["fixed_ids"])
            fb = set(paired(base_val, R / "raw_k3_halfB")["fixed_ids"])
            L.append(f"\nReproducibility: half A fixed {len(fa)}, half B fixed {len(fb)}, both fixed {len(fa & fb)}.\n")

        att = attribute(base_val, R / "raw_k3", bird_dir)
        hit = [a for a in att if a["supplied"]]
        L.append(f"\n## Attribution proxy (raw retrieval vs no-memory, val)\n\n"
                 f"{len(hit)} of {len(att)} fixed items used an identifier or constant that the gold query needs, "
                 f"the baseline missed, and a retrieved experience contained. Check by hand with "
                 f"`memorygate inspect nomem_r1 raw_k3`.\n")
        L.append("| qid | db | supplied by memory | memories |\n|---|---|---|---|")
        for a in hit[:25]:
            L.append(f"| {a['qid']} | {a['db_id']} | `{', '.join(a['supplied'][:6])}` | {', '.join(a['memory_ids'])} |")

    # per-db headroom
    if have("nomem_r1") and have("evid_r1"):
        a = {r["qid"]: r for r in load_traj(R / "nomem_r1") if not r["gold_error"]}
        b = {r["qid"]: r for r in load_traj(R / "evid_r1") if not r["gold_error"]}
        dbs: dict[str, list] = {}
        for q in a.keys() & b.keys():
            dbs.setdefault(a[q]["db_id"], []).append((a[q]["correct"], b[q]["correct"]))
        L.append("\n## Headroom by database (learn+val)\n\n| db | n | no-memory | official hints | Δ |\n|---|---|---|---|---|")
        for db, xs in sorted(dbs.items(), key=lambda kv: -(sum(y for _, y in kv[1]) - sum(x for x, _ in kv[1])) / len(kv[1])):
            na, nb = sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)
            L.append(f"| {db} | {len(xs)} | {na:.3f} | {nb:.3f} | {nb - na:+.3f} |")

    # cost
    calls, usd, tin, tout, tthink, lat = 0, 0.0, 0, 0, 0, []
    for u in R.glob("*/usage.jsonl"):
        if u.parent.name.startswith("_"):
            continue
        for line in u.read_text().splitlines():
            r = json.loads(line)
            calls += 1; usd += r["cost_usd"]; tin += r["input_tokens"]; tout += r["output_tokens"]
            tthink += r["thinking_tokens"]; lat.append(r["latency_s"])
    if calls:
        per = usd / calls
        lat.sort()
        L.append(f"\n## Cost\n\n- Week-1 total: {calls} calls, ${usd:.2f}; per call ${per:.5f}, "
                 f"{tin / calls:.0f} input / {tout / calls:.0f} output / {tthink / calls:.0f} thinking tokens; "
                 f"median latency {lat[len(lat) // 2]:.2f}s.")
        full = 70_000
        L.append(f"- Projection for the full plan (≈{full:,} solve calls: 12 rounds × 4 groups × 3 orders, gate runs "
                 f"old+new memory on val each round, test every other round): about ${full * per * 1.3:.0f} "
                 f"(×1.3 for longer memory prompts and consolidation calls).")
    text = "\n".join(L) + "\n"
    Path(out_path).write_text(text)
    return text
