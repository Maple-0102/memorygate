"""Execution-accuracy grading.

`correct` follows the BIRD official rule: set(pred_rows) == set(gold_rows), so row order and
duplicates are ignored. `strict` additionally compares row multiplicity, and is recorded only
for analysis. A gold query that fails or times out makes the item ungradable (`gold_error`),
and it is excluded from accuracy rather than counted wrong.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .sqlexec import execute


@dataclass
class Grade:
    correct: bool
    strict: bool
    pred_error: str | None
    gold_error: str | None
    n_pred_rows: int
    n_gold_rows: int


def compare(pred_rows: list[tuple], gold_rows: list[tuple]) -> tuple[bool, bool]:
    loose = set(pred_rows) == set(gold_rows)
    strict = Counter(pred_rows) == Counter(gold_rows)
    return loose, strict


def grade(db_path: str | Path, pred_sql: str | None, gold_sql: str, timeout_s: float = 30.0, max_rows: int = 100_000) -> Grade:
    gold = execute(db_path, gold_sql, timeout_s, max_rows)
    if not gold.ok:
        return Grade(False, False, None, gold.error, 0, 0)
    if not pred_sql or not pred_sql.strip():
        return Grade(False, False, "no SQL produced", None, 0, len(gold.rows))
    pred = execute(db_path, pred_sql, timeout_s, max_rows)
    if not pred.ok:
        return Grade(False, False, pred.error, None, 0, len(gold.rows))
    loose, strict = compare(pred.rows, gold.rows)
    return Grade(loose, strict, None, None, len(pred.rows), len(gold.rows))
