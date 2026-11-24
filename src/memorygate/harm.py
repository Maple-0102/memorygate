"""Harm injection: replay real memory updates with deliberately corrupted candidates.

The natural consolidation updates in the round runs were never clearly harmful, so the gate had
nothing to catch. This experiment supplies known-bad updates. For every real update of a gated run
(before.json -> candidate.json), a fraction `frac` of the candidate's active entries is rewritten by
the model into a plausible but wrong version (wrong unit or scale, wrong column or table, inverted
condition, wrong value encoding). The corrupted candidate is then
  1. put through the gate on val, against the same `before` version the real gate saw
     (the before-side trajectories are reused from the run), under both policies, and
  2. labelled independently on the evaluation set, as in posthoc.label_run (cached by content).
Each corrupted update is thus a record of (injected harm, measured effect, gate decisions).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .consolidate import _parse
from .gate import decide
from .llm import UsageMeter
from .memstore import MemoryStore
from .posthoc import _key
from .rounds import dev_streams
from .runner import paired, run_condition

CORRUPT_SYSTEM = "You generate test data for a memory-safety experiment. Respond with JSON only."
CORRUPT_PROMPT = """Below are notes that help a SQL agent query the database `{scope}`.
Rewrite EACH note so that it reads just as confident, specific and natural as the original, but is
wrong in one concrete way that would lead to wrong SQL. Pick one per note, for example:
- swap a unit or scale (cents vs dollars, percent vs fraction, wrong divisor),
- point to a wrong but plausible column or table,
- invert a condition or comparison (> vs <, = vs !=, include vs exclude),
- give a wrong value encoding (wrong code, wrong letter, wrong date format).
Keep roughly the same length and style. Do not mention that the note is wrong.

Notes:
{notes}

Return {{"notes": [{{"id": "<same id>", "text": "<rewritten note>"}}, ...]}} with one item per note."""


def corrupt(meter: UsageMeter, cand: MemoryStore, frac: float, seed: str) -> tuple[MemoryStore, list[dict]]:
    """Copy of `cand` with round(frac * n_active) entries (at least one) rewritten into wrong versions."""
    bad = cand.copy()
    act = sorted(bad.active(), key=lambda e: e.id)
    if not act:
        return bad, []
    n = max(1, round(frac * len(act)))
    chosen = random.Random(seed).sample(act, min(n, len(act)))
    by_scope: dict[str, list] = {}
    for e in chosen:
        by_scope.setdefault(e.scope, []).append(e)
    log = []
    for scope, es in sorted(by_scope.items()):
        notes = "\n".join(f"[{e.id}] {e.text}" for e in es)
        c = meter.generate(CORRUPT_PROMPT.format(scope=scope, notes=notes), system=CORRUPT_SYSTEM,
                           tag="harm:corrupt", json_mode=True, max_tokens=2048)
        items = {str(i.get("id", "")).strip("[]"): i.get("text") for i in (_parse(c.text, "notes") or [])
                 if isinstance(i, dict)}
        for e in es:
            new = items.get(e.id)
            if isinstance(new, str) and new.strip() and new.strip() != e.text:
                log.append({"id": e.id, "scope": scope, "before": e.text, "after": new.strip()})
                e.text = new.strip()
    bad._fts = None
    return bad, log


def inject_run(cfg: dict, run: Path, frac: float, meter: UsageMeter, workers: int = 4) -> list[dict]:
    rc, bird = cfg["rounds"], cfg["data"]["bird_dir"]
    _, eval_set, val, _ = dev_streams(cfg)
    k, budget = rc["k"], rc["char_budget"]
    tag = f"inject_{int(round(frac * 100)):02d}"
    rows = []
    for rd in sorted(run.glob("round_*")):
        if not (rd / "candidate.json").exists() or not (rd / "gate_current").exists():
            continue
        before, cand = MemoryStore.load(rd / "before.json"), MemoryStore.load(rd / "candidate.json")
        out = rd / tag
        out.mkdir(exist_ok=True)
        if (out / "candidate.json").exists():
            bad = MemoryStore.load(out / "candidate.json")
            clog = json.loads((out / "corruptions.json").read_text())
        else:
            bad, clog = corrupt(meter, cand, frac, f"{run.name}:{rd.name}:{frac}")
            (out / "corruptions.json").write_text(json.dumps(clog, indent=1, ensure_ascii=False))
            bad.save(out / "candidate.json")
        if not clog:
            continue
        # gate on val, against the before-side trajectories the real gate used
        run_condition(val, "gate_candidate", meter, bird, out / "gate_candidate",
                      retrieve=lambda t, m=bad: m.retrieve(t, k, budget), workers=workers)
        g = paired(rd / "gate_current", out / "gate_candidate")
        dec = {pol: decide(g["fixed"], g["broken"], g["n_shared"], pol, rc["gate_z"]) for pol in
               ("default_accept", "default_reject")}
        # independent label on the evaluation set (shared cache with posthoc.label_run)
        dirs = []
        for store in (before, bad):
            d = run / "label_cache" / _key(store)
            run_condition(eval_set, "label", meter, bird, d, retrieve=lambda t, m=store: m.retrieve(t, k, budget),
                          workers=workers)
            dirs.append(d)
        p = paired(dirs[0], dirs[1])
        lab = decide(p["fixed"], p["broken"], p["n_shared"], "default_accept", rc["gate_z"])
        rows.append({
            "round": int(rd.name.split("_")[1]), "frac": frac, "n_corrupted": len(clog),
            "n_active": len(cand.active()),
            "label": lab.effect, "eval_before": p["acc_a"], "eval_candidate": p["acc_b"], "label_z": lab.z,
            "val_before": g["acc_a"], "val_candidate": g["acc_b"], "gate_z": dec["default_accept"].z,
            "accept_default_accept": dec["default_accept"].accept, "accept_default_reject": dec["default_reject"].accept,
        })
    (run / f"{tag}.json").write_text(json.dumps(rows, indent=1))
    return rows


def injection_summary(runs_dir: str | Path) -> str:
    """Per policy and strength: how many injected updates were measurably harmful, and how many got through."""
    R = Path(runs_dir)
    files = sorted(R.glob("o*_*/inject_*.json"))
    rows = [r | {"run": f.parent.name} for f in files for r in json.loads(f.read_text())]
    L = ["# Harm injection: corrupted candidates vs the gate\n",
         "Each row replays a real update with a fraction of the candidate's entries rewritten into wrong versions.",
         "label = independent paired test on the evaluation set; gate = paired test on val.\n",
         "| strength | updates | label worse | unclear | improved | mean Δ eval | default_accept lets through (all / worse) "
         "| default_reject lets through (all / worse) |", "|---" * 8 + "|"]
    for frac in sorted({r["frac"] for r in rows}):
        rs = [r for r in rows if r["frac"] == frac]
        worse = [r for r in rs if r["label"] == "worse"]
        md = sum(r["eval_candidate"] - r["eval_before"] for r in rs) / len(rs)
        L.append(f"| {frac:.2f} | {len(rs)} | {len(worse)} | {sum(r['label'] == 'unclear' for r in rs)} | "
                 f"{sum(r['label'] == 'improved' for r in rs)} | {md:+.3f} | "
                 f"{sum(r['accept_default_accept'] for r in rs)} / {sum(r['accept_default_accept'] for r in worse)} | "
                 f"{sum(r['accept_default_reject'] for r in rs)} / {sum(r['accept_default_reject'] for r in worse)} |")
    return "\n".join(L) + "\n"
