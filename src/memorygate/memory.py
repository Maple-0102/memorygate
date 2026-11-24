"""Raw-experience bank: store past trajectories as-is, retrieve by database + keywords.

An experience is what the agent saw on a learning task, plus the correct answer it was
given afterwards (the plan's "user acceptance" assumption):
    question, the agent's own SQL and error if it failed, and the correct SQL.
The official BIRD hint of a learning task is NOT stored, so any gain must come from
the experience itself, not from copying hints.

Retrieval is SQLite FTS5 (BM25, porter stemming) over the question and the correct SQL
(so table/column names count), restricted to the same db_id.
The `shuffled` control retrieves k random experiences from the same database instead,
to separate "relevant past experience helps" from "any extra same-db context helps".
"""
from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass

from .data import Task

_WORD = re.compile(r"[A-Za-z0-9_]{3,}")
_STOP = {"the", "and", "for", "what", "which", "how", "many", "with", "are", "was", "that", "this",
         "list", "name", "give", "from", "all", "among", "please", "their", "there", "have", "has"}


@dataclass(frozen=True)
class Experience:
    qid: str
    db_id: str
    question: str
    correct_sql: str
    agent_sql: str | None = None
    agent_error: str | None = None
    agent_correct: bool | None = None

    def render(self) -> str:
        lines = [f"Past question: {self.question}"]
        if self.agent_correct is False:
            tried = self.agent_sql or "(no SQL)"
            lines.append(f"Earlier wrong attempt: {tried}" + (f"  [error: {self.agent_error}]" if self.agent_error else ""))
        lines.append(f"Correct SQL: {self.correct_sql}")
        return "\n  ".join(lines)


class ExperienceBank:
    def __init__(self, experiences: list[Experience]):
        self.items = {e.qid: e for e in experiences}
        self.by_db: dict[str, list[str]] = {}
        for e in experiences:
            self.by_db.setdefault(e.db_id, []).append(e.qid)
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.execute("CREATE VIRTUAL TABLE exp USING fts5(qid UNINDEXED, db_id UNINDEXED, question, sql, tokenize='porter unicode61')")
        self._db.executemany("INSERT INTO exp VALUES (?,?,?,?)", [(e.qid, e.db_id, e.question, e.correct_sql) for e in experiences])

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_tasks(cls, tasks: list[Task], attempts: dict[str, dict] | None = None) -> "ExperienceBank":
        attempts = attempts or {}
        exps = []
        for t in tasks:
            a = attempts.get(t.qid, {})
            if a.get("gold_error"):
                continue  # an unverifiable answer is not a usable experience
            exps.append(Experience(t.qid, t.db_id, t.question, t.gold_sql,
                                   a.get("pred_sql"), a.get("pred_error"), a.get("correct")))
        return cls(exps)

    def retrieve(self, task: Task, k: int) -> list[Experience]:
        terms = [w for w in dict.fromkeys(_WORD.findall(task.question.lower())) if w not in _STOP]
        if not terms or k <= 0:
            return []
        query = " OR ".join(f'"{w}"' for w in terms)
        rows = self._db.execute(
            "SELECT qid FROM exp WHERE exp MATCH ? AND db_id = ? AND qid != ? ORDER BY bm25(exp) LIMIT ?",
            (query, task.db_id, task.qid, k),
        ).fetchall()
        return [self.items[r[0]] for r in rows]

    def random_same_db(self, task: Task, k: int, seed: int) -> list[Experience]:
        pool = sorted(q for q in self.by_db.get(task.db_id, []) if q != task.qid)
        rng = random.Random(f"{seed}:{task.qid}")
        return [self.items[q] for q in rng.sample(pool, min(k, len(pool)))]
