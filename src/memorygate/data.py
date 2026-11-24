"""BIRD dev loader and schema rendering.

Expected layout (unzipped from the official BIRD dev release):
    <bird_dir>/dev.json
    <bird_dir>/dev_databases/<db_id>/<db_id>.sqlite
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Task:
    qid: str
    db_id: str
    question: str
    evidence: str
    gold_sql: str
    difficulty: str


def load_bird(bird_dir: str | Path) -> list[Task]:
    bird_dir = Path(bird_dir)
    raw = json.loads((bird_dir / "dev.json").read_text())
    tasks = []
    for i, r in enumerate(raw):
        qid = r.get("question_id", i)
        tasks.append(
            Task(
                qid=f"T{int(qid):04d}",
                db_id=r["db_id"],
                question=r["question"],
                evidence=r.get("evidence", "") or "",
                gold_sql=r["SQL"],
                difficulty=r.get("difficulty", ""),
            )
        )
    return tasks


def db_path(bird_dir: str | Path, db_id: str) -> Path:
    return Path(bird_dir) / "dev_databases" / db_id / f"{db_id}.sqlite"


@lru_cache(maxsize=64)
def schema_ddl(path: str) -> str:
    """CREATE statements for all user tables, as stored in sqlite_master."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return "\n\n".join(r[0].strip() + ";" for r in rows)
