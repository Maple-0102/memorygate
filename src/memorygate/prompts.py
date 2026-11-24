"""Prompt assembly and SQL extraction.

Order is schema first (stable per database, so it can hit the provider's prompt cache),
then hints/memories, then the question.
"""
from __future__ import annotations

import re

SYSTEM = (
    "You are an expert SQLite analyst. Given a database schema and a question, "
    "write one SQLite query that answers it. Return only the query in a ```sql code block."
)


def build_prompt(schema: str, question: str, hints: list[str] | None = None, hint_label: str = "Hints") -> str:
    parts = [f"### Database schema\n{schema}"]
    hints = [h for h in (hints or []) if h and h.strip()]
    if hints:
        body = "\n".join(f"- {h.strip()}" for h in hints)
        parts.append(f"### {hint_label}\n{body}")
    parts.append(f"### Question\n{question.strip()}")
    parts.append("### SQL")
    return "\n\n".join(parts)


_FENCE = re.compile(r"```(?:sql|sqlite)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str | None:
    if not text:
        return None
    blocks = _FENCE.findall(text)
    sql = blocks[-1] if blocks else text
    sql = sql.strip().rstrip(";").strip()
    if not re.match(r"^(with|select)\b", sql, re.IGNORECASE):
        m = re.search(r"\b(with|select)\b.*", sql, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        sql = m.group(0).strip().rstrip(";").strip()
    return sql or None
