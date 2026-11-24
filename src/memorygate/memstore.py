"""Versioned, structured memory (the plan's data structure).

Each entry:
    {"id": "L0042", "scope": "db:california_schools", "text": "...", "evidence_tasks": ["T0113"],
     "created_round": 3, "uses": 9, "wins": 7, "losses": 2, "status": "active"}

status: active | quarantined (rejected by the gate) | retired (consolidated away or pruned).
Nothing is deleted; every version is saved as a readable JSON file.
Retrieval filters by scope first (this db, or global), then ranks by BM25 over the text,
and fills a character budget so every group gets the same context budget.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .data import Task

_WORD = re.compile(r"[A-Za-z0-9_]{3,}")
_STOP = {"the", "and", "for", "what", "which", "how", "many", "with", "are", "was", "that", "this",
         "list", "name", "give", "from", "all", "among", "please", "their", "there", "have", "has"}


def fts_query(text: str) -> str | None:
    terms = [w for w in dict.fromkeys(_WORD.findall(text.lower())) if w not in _STOP]
    return " OR ".join(f'"{w}"' for w in terms) if terms else None


@dataclass
class Entry:
    id: str
    scope: str
    text: str
    evidence_tasks: list[str] = field(default_factory=list)
    created_round: int = 0
    uses: int = 0
    wins: int = 0
    losses: int = 0
    status: str = "active"
    merged_from: list[str] = field(default_factory=list)

    @property
    def qid(self) -> str:  # runner records retrieved ids under memory_ids
        return self.id

    def render(self) -> str:
        return self.text


class MemoryStore:
    def __init__(self, entries: list[Entry] | None = None, version: int = 0, next_id: int = 1):
        self.entries: dict[str, Entry] = {e.id: e for e in (entries or [])}
        self.version = version
        self.next_id = next_id
        self._fts: sqlite3.Connection | None = None

    # ---- bookkeeping -------------------------------------------------------------------------
    def copy(self) -> "MemoryStore":
        return MemoryStore([copy.deepcopy(e) for e in self.entries.values()], self.version, self.next_id)

    def new_id(self) -> str:
        i = self.next_id
        self.next_id += 1
        return f"L{i:04d}"

    def add(self, scope: str, text: str, evidence: list[str], round_: int, merged_from: list[str] | None = None) -> Entry:
        e = Entry(self.new_id(), scope, text.strip(), list(evidence), round_, merged_from=list(merged_from or []))
        self.entries[e.id] = e
        self._fts = None
        return e

    def active(self, scope: str | None = None) -> list[Entry]:
        return [e for e in self.entries.values() if e.status == "active" and (scope is None or e.scope == scope)]

    def set_status(self, ids, status: str) -> None:
        for i in ids:
            self.entries[i].status = status
        self._fts = None

    def record_outcome(self, ids: list[str], correct: bool) -> None:
        for i in ids:
            e = self.entries.get(i)
            if e is None:
                continue
            e.uses += 1
            if correct:
                e.wins += 1
            else:
                e.losses += 1

    def tokens(self) -> int:
        return sum(len(e.text) for e in self.active()) // 4

    # ---- persistence -------------------------------------------------------------------------
    def to_json(self) -> dict:
        return {"version": self.version, "next_id": self.next_id, "entries": [asdict(e) for e in self.entries.values()]}

    @classmethod
    def from_json(cls, d: dict) -> "MemoryStore":
        return cls([Entry(**e) for e in d["entries"]], d["version"], d["next_id"])

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_json(), indent=1, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> "MemoryStore":
        return cls.from_json(json.loads(Path(path).read_text()))

    # ---- retrieval ---------------------------------------------------------------------------
    def _index(self) -> sqlite3.Connection:
        if self._fts is None:
            db = sqlite3.connect(":memory:", check_same_thread=False)
            db.execute("CREATE VIRTUAL TABLE m USING fts5(id UNINDEXED, scope UNINDEXED, text, tokenize='porter unicode61')")
            db.executemany("INSERT INTO m VALUES (?,?,?)", [(e.id, e.scope, e.text) for e in self.active()])
            self._fts = db
        return self._fts

    def retrieve(self, task: Task, k: int, char_budget: int) -> list[Entry]:
        q = fts_query(task.question)
        if not q or k <= 0:
            return []
        rows = self._index().execute(
            "SELECT id FROM m WHERE m MATCH ? AND scope IN (?, 'global') ORDER BY bm25(m) LIMIT ?",
            (q, f"db:{task.db_id}", k * 3),
        ).fetchall()
        return fit_budget([self.entries[r[0]] for r in rows], k, char_budget)


def fit_budget(items: list, k: int, char_budget: int) -> list:
    out, used = [], 0
    for it in items:
        n = len(it.render())
        if len(out) >= k:
            break
        if used + n > char_budget and out:
            continue
        out.append(it)
        used += n
    return out


def diff(old: MemoryStore, new: MemoryStore) -> dict:
    """What changed between two versions: added, retired, quarantined, and merges."""
    old_active = {e.id for e in old.active()}
    new_active = {e.id for e in new.active()}
    added = sorted(new_active - old_active)
    removed = sorted(old_active - new_active)
    merges = [{"id": i, "from": new.entries[i].merged_from} for i in added if len(new.entries[i].merged_from) > 1]
    return {
        "added": [{"id": i, "scope": new.entries[i].scope, "text": new.entries[i].text} for i in added],
        "removed": [{"id": i, "status": new.entries[i].status if i in new.entries else "missing",
                     "text": old.entries[i].text} for i in removed],
        "merges": merges,
        "n_active_before": len(old_active),
        "n_active_after": len(new_active),
    }
