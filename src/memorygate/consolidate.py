"""Dreaming-style consolidation, two LLM steps per database per round.

1. distill   : read this round's failed trajectories (with the correct SQL revealed afterwards) and write
               candidate lessons: reusable facts about fields, value encodings, formulas, join paths.
2. consolidate: merge the candidates into the current entries for that scope: dedupe, resolve conflicts,
               respect a capacity cap. Entries that are not carried over are retired (kept in history).

A deterministic prune runs first: entries retrieved often but mostly on wrong answers are retired.
Both steps produce a CANDIDATE store; whether it takes effect is decided elsewhere (gate or not).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from .data import Task, db_path, schema_ddl
from .llm import UsageMeter
from .memstore import MemoryStore

DISTILL_SYSTEM = (
    "You maintain a knowledge base that helps an agent write SQLite queries for one database. "
    "You extract short, reusable lessons from the agent's past mistakes. Respond with JSON only."
)

DISTILL_PROMPT = """Database: {db_id}

### Schema
{schema}

### Past tasks the agent got wrong (the correct SQL was revealed afterwards)
{items}

Write at most {max_lessons} lessons that would help on OTHER future questions about this database.
Good lessons state a reusable fact: what a column or value means (e.g. "triple bond is bond_type = '#'"),
how a quantity is computed (a formula with exact column names), which join path connects two tables,
or a filtering convention. Use exact table, column and value spellings from the schema and correct SQL.
Do not write lessons that only restate one question's answer. Each lesson is one or two sentences.
Set scope to "db" for facts about this database, or "global" only for general SQLite advice.

Return JSON: {{"lessons": [{{"text": "...", "scope": "db" | "global", "evidence_tasks": ["T0001", ...]}}]}}"""

CONSOLIDATE_SYSTEM = "You curate a knowledge base for a SQL agent. Respond with JSON only."

CONSOLIDATE_PROMPT = """Scope: {scope}

### Current entries
{current}

### New candidate entries
{candidates}

Produce the consolidated list for this scope, at most {cap} entries:
- Merge entries that say the same thing into one; list every merged id in "sources".
- If two entries contradict each other, keep the one better supported (more wins, more evidence) and drop the other.
- Keep a current entry unchanged by returning its exact text with "sources": ["<its id>"].
- Drop entries that are vague or only restate one question's answer.
- Do not invent facts that are not in the entries above.

Return JSON: {{"entries": [{{"text": "...", "sources": ["L0001", "N1", ...]}}]}}"""


def _parse(text: str, key: str) -> list[dict] | None:
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        s, e = (text or "").find("{"), (text or "").rfind("}")
        if s < 0 or e <= s:
            return None
        try:
            d = json.loads(text[s : e + 1])
        except json.JSONDecodeError:
            return None
    items = d.get(key) if isinstance(d, dict) else None
    return items if isinstance(items, list) else None


def distill(meter: UsageMeter, bird_dir: str, db_id: str, trajs: list[dict], gold: dict[str, Task],
            max_items: int = 15, max_lessons: int = 5) -> tuple[list[dict], dict]:
    fails = [r for r in trajs if not r["correct"] and not r["gold_error"]][:max_items]
    if not fails:
        return [], {"db": db_id, "n_failed": 0}
    items = []
    for r in fails:
        line = f"- [{r['qid']}] Q: {gold[r['qid']].question}\n  agent SQL: {r['pred_sql'] or '(none)'}"
        if r.get("pred_error"):
            line += f"\n  error: {r['pred_error']}"
        line += f"\n  correct SQL: {gold[r['qid']].gold_sql}"
        items.append(line)
    prompt = DISTILL_PROMPT.format(db_id=db_id, schema=schema_ddl(str(db_path(bird_dir, db_id))),
                                   items="\n".join(items), max_lessons=max_lessons)
    comp = meter.generate(prompt, DISTILL_SYSTEM, tag="distill", json_mode=True, max_tokens=2048)
    lessons = _parse(comp.text, "lessons")
    valid_ids = {r["qid"] for r in fails}
    out = []
    for l in lessons or []:
        if not isinstance(l, dict) or not str(l.get("text", "")).strip():
            continue
        ev = [q for q in l.get("evidence_tasks", []) if q in valid_ids] or [fails[0]["qid"]]
        scope = "global" if l.get("scope") == "global" else f"db:{db_id}"
        out.append({"text": str(l["text"]).strip(), "scope": scope, "evidence_tasks": ev})
    return out[:max_lessons], {"db": db_id, "n_failed": len(fails), "n_lessons": len(out), "parse_ok": lessons is not None}


def prune(store: MemoryStore, min_uses: int, loss_ratio: float) -> list[str]:
    """Retire entries with uses >= min_uses whose losses exceed loss_ratio * wins."""
    gone = [e.id for e in store.active() if e.uses >= min_uses and e.losses > loss_ratio * max(e.wins, 1)]
    store.set_status(gone, "retired")
    return gone


def consolidate_scope(meter: UsageMeter, store: MemoryStore, scope: str, candidates: list[dict], round_: int,
                      cap: int) -> dict:
    """Mutates `store` for one scope. Returns a log dict."""
    current = store.active(scope)
    if not candidates and len(current) <= cap:
        return {"scope": scope, "llm": False}
    if not current:  # nothing to merge into: add up to cap directly
        for c in candidates[:cap]:
            store.add(scope, c["text"], c["evidence_tasks"], round_)
        return {"scope": scope, "llm": False, "added": min(len(candidates), cap)}

    cand_ids = {f"N{i + 1}": c for i, c in enumerate(candidates)}
    cur_txt = "\n".join(f'- {e.id} (uses {e.uses}, wins {e.wins}, losses {e.losses}): {e.text}' for e in current) or "(none)"
    new_txt = "\n".join(f"- {k} (evidence {', '.join(c['evidence_tasks'])}): {c['text']}" for k, c in cand_ids.items()) or "(none)"
    comp = meter.generate(CONSOLIDATE_PROMPT.format(scope=scope, current=cur_txt, candidates=new_txt, cap=cap),
                          CONSOLIDATE_SYSTEM, tag="consolidate", json_mode=True, max_tokens=4096)
    result = _parse(comp.text, "entries")
    cur_by_id = {e.id: e for e in current}

    if result is None:  # fallback: keep everything, append candidates, drop oldest beyond cap
        for c in candidates:
            store.add(scope, c["text"], c["evidence_tasks"], round_)
        over = sorted(store.active(scope), key=lambda e: (e.wins - e.losses, e.created_round))
        store.set_status([e.id for e in over[: max(0, len(over) - cap)]], "retired")
        return {"scope": scope, "llm": True, "parse_ok": False}

    kept: set[str] = set()
    n_new = 0
    for item in result[:cap]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        srcs = [s for s in item.get("sources", []) if s in cur_by_id or s in cand_ids]
        if not srcs:
            continue  # unsupported by any input entry: refuse invented content
        text = str(item["text"]).strip()
        if len(srcs) == 1 and srcs[0] in cur_by_id and cur_by_id[srcs[0]].text == text:
            kept.add(srcs[0])
            continue
        ev, uses, wins, losses = [], 0, 0, 0
        for s in srcs:
            if s in cur_by_id:
                e = cur_by_id[s]
                ev += e.evidence_tasks; uses += e.uses; wins += e.wins; losses += e.losses
            else:
                ev += cand_ids[s]["evidence_tasks"]
        e = store.add(scope, text, sorted(set(ev)), round_, merged_from=srcs)
        e.uses, e.wins, e.losses = uses, wins, losses
        n_new += 1
    retired = [i for i in cur_by_id if i not in kept]
    store.set_status(retired, "retired")
    return {"scope": scope, "llm": True, "parse_ok": True, "kept": len(kept), "new_or_merged": n_new, "retired": len(retired)}


def consolidate_round(meter: UsageMeter, store: MemoryStore, bird_dir: str, trajs: list[dict], gold: dict[str, Task],
                      round_: int, cfg: dict, workers: int = 8) -> tuple[MemoryStore, dict]:
    """Returns a new candidate store (the input store is not modified) and a log."""
    cand = store.copy()
    cand.version = store.version + 1
    pruned = prune(cand, cfg.get("prune_min_uses", 6), cfg.get("prune_loss_ratio", 2.0))
    by_db: dict[str, list[dict]] = {}
    for r in trajs:
        by_db.setdefault(r["db_id"], []).append(r)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        distilled = list(pool.map(lambda kv: distill(meter, bird_dir, kv[0], kv[1], gold,
                                                     cfg.get("distill_max_items", 15), cfg.get("distill_max_lessons", 5)),
                                  sorted(by_db.items())))
    by_scope: dict[str, list[dict]] = {}
    for lessons, _ in distilled:
        for l in lessons:
            by_scope.setdefault(l["scope"], []).append(l)
    # scopes with new lessons, plus any scope over capacity
    scopes = set(by_scope) | {e.scope for e in cand.active()}
    caps = {s: (cfg.get("cap_global", 10) if s == "global" else cfg.get("cap_per_db", 25)) for s in scopes}
    logs = []
    # consolidation mutates the shared store: run scopes one at a time (each is one call)
    for s in sorted(scopes):
        logs.append(consolidate_scope(meter, cand, s, by_scope.get(s, []), round_, caps[s]))
    return cand, {"pruned": pruned, "distill": [d for _, d in distilled], "consolidate": logs}
