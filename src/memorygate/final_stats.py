"""Supplementary statistics for the final comparison (added after the design freeze, before any test score was seen).

The primary analysis is posthoc.final_summary, unchanged. This adds, for the same 7 pre-registered pairs and the same unit
(test question, correctness averaged over task orders):
  - the difference in percentage points with a 95% interval from the per-question differences,
  - the raw two-sided p value and the Holm-adjusted p value over all 7 pairs (supplementary),
  - each task order's own accuracies and difference, and whether all orders agree in sign.
Usage: python -m memorygate.final_stats [runs_dir] [out_path]
"""
from __future__ import annotations

import sys
from math import erfc, sqrt
from pathlib import Path

from .posthoc import FINAL_PAIRS
from .runner import load_traj

GROUPS = ("no_memory", "raw", "consolidate", "gate_accept", "gate_reject")


def holm(ps: list[float]) -> list[float]:
    m, order = len(ps), sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def last_evals(R: Path) -> tuple[list[str], dict[str, dict[str, dict[str, bool]]]]:
    orders = sorted({p.name.split("_")[0] for p in R.glob("o*_*") if p.is_dir()})
    res: dict[str, dict[str, dict[str, bool]]] = {g: {} for g in GROUPS}
    for o in orders:
        for g in GROUPS:
            ds = sorted((R / f"{o}_{g}").glob("round_*/eval"))
            if ds:
                res[g][o] = {r["qid"]: r["correct"] for r in load_traj(ds[-1]) if not r["gold_error"]}
    return orders, res


def compare(res, orders, a: str, b: str) -> dict | None:
    os_ = [o for o in orders if o in res[a] and o in res[b]]
    if not os_:
        return None
    qs = sorted(set.intersection(*(set(res[g][o]) for g in (a, b) for o in os_)))
    d = [sum(res[b][o][q] - res[a][o][q] for o in os_) / len(os_) for q in qs]
    n = len(d)
    md = sum(d) / n
    se = sqrt(sum((x - md) ** 2 for x in d) / (n - 1) / n) if n > 1 else 0.0
    z = md / se if se > 0 else 0.0
    per = {o: (sum(res[a][o][q] for q in qs) / n, sum(res[b][o][q] for q in qs) / n) for o in os_}
    return {"pair": f"{b} vs {a}", "n": n, "orders": os_, "acc_a": sum(p[0] for p in per.values()) / len(per),
            "acc_b": sum(p[1] for p in per.values()) / len(per), "diff": md, "lo": md - 1.96 * se,
            "hi": md + 1.96 * se, "z": z, "p": erfc(abs(z) / sqrt(2)), "per_order": per}


def report(runs_dir: str | Path) -> str:
    orders, res = last_evals(Path(runs_dir))
    rows = [r for a, b in FINAL_PAIRS if (r := compare(res, orders, a, b))]
    for r, p in zip(rows, holm([r["p"] for r in rows])):
        r["p_holm"] = p
    pp = lambda x: f"{100 * x:+.1f}"
    L = ["# Final comparison: intervals, per-order results, Holm (supplementary)\n",
         f"Orders: {', '.join(orders)}. Last evaluated round. Unit = test question, correctness averaged over orders. "
         "Δ in percentage points with 95% interval from per-question differences. p = two-sided, raw; "
         "Holm over the 7 pre-registered pairs is supplementary. Primary verdicts: reports/final.md.\n",
         "| B vs A | n | acc A | acc B | Δ pt | 95% interval | z | p | p (Holm) | same sign in every order |",
         "|---" * 10 + "|"]
    for r in rows:
        signs = {(b > a) - (b < a) for a, b in r["per_order"].values()}
        L.append(f"| {r['pair']} | {r['n']} | {r['acc_a']:.3f} | {r['acc_b']:.3f} | {pp(r['diff'])} | "
                 f"[{pp(r['lo'])}, {pp(r['hi'])}] | {r['z']:+.2f} | {r['p']:.4f} | {r['p_holm']:.4f} | "
                 f"{'yes' if len(signs) == 1 and 0 not in signs else 'no'} |")
    L += ["\n## Per task order\n", "| B vs A | " + " | ".join(f"{o}: A → B (Δ pt)" for o in orders) + " |",
          "|---" * (len(orders) + 1) + "|"]
    for r in rows:
        L.append(f"| {r['pair']} | " + " | ".join(
            f"{a:.3f} → {b:.3f} ({pp(b - a)})" if (a, b) else "" for a, b in
            (r["per_order"].get(o, (None, None)) for o in orders)) + " |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    runs = sys.argv[1] if len(sys.argv) > 1 else "runs/final"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "reports/final_stats.md")
    text = report(runs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(text)
