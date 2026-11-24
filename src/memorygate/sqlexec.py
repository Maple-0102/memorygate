"""Read-only SQLite execution with a wall-clock timeout and a row cap."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecResult:
    ok: bool
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False
    elapsed_s: float = 0.0


def execute(db_path: str | Path, sql: str, timeout_s: float = 30.0, max_rows: int = 100_000) -> ExecResult:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    t0 = time.time()
    deadline = t0 + timeout_s
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    except sqlite3.Error as e:
        return ExecResult(ok=False, error=f"connect: {e}")
    # Returning non-zero from the progress handler aborts the running statement.
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        return ExecResult(ok=True, rows=rows[:max_rows], truncated=truncated, elapsed_s=time.time() - t0)
    except sqlite3.OperationalError as e:
        msg = "timeout" if time.time() > deadline else str(e)
        return ExecResult(ok=False, error=msg, elapsed_s=time.time() - t0)
    except (sqlite3.Error, sqlite3.Warning, ValueError) as e:
        return ExecResult(ok=False, error=f"{type(e).__name__}: {e}", elapsed_s=time.time() - t0)
    finally:
        conn.close()
