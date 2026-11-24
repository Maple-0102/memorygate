import json
import sqlite3

import pytest


@pytest.fixture
def bird_dir(tmp_path):
    """A tiny BIRD-shaped dataset: two databases, eight questions."""
    root = tmp_path / "bird"
    for db in ("shop", "school"):
        d = root / "dev_databases" / db
        d.mkdir(parents=True)
        conn = sqlite3.connect(d / f"{db}.sqlite")
        if db == "shop":
            conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount_cents INTEGER, city TEXT)")
            conn.executemany("INSERT INTO orders VALUES (?,?,?)", [(1, 1000, "A"), (2, 2500, "B"), (3, 500, "A")])
        else:
            conn.execute("CREATE TABLE frpm (school TEXT, free_meal INTEGER, enrollment INTEGER)")
            conn.executemany("INSERT INTO frpm VALUES (?,?,?)", [("x", 50, 100), ("y", 30, 60)])
        conn.commit()
        conn.close()
    qs = [
        ("shop", "How many orders?", "", "SELECT COUNT(*) FROM orders"),
        ("shop", "Total amount in dollars?", "amount is stored in cents", "SELECT SUM(amount_cents) / 100.0 FROM orders"),
        ("shop", "Cities with orders?", "", "SELECT DISTINCT city FROM orders"),
        ("shop", "Largest order id?", "", "SELECT id FROM orders ORDER BY amount_cents DESC LIMIT 1"),
        ("school", "How many schools?", "", "SELECT COUNT(*) FROM frpm"),
        ("school", "Free meal rate of x?", "rate = free_meal / enrollment", "SELECT CAST(free_meal AS REAL) / enrollment FROM frpm WHERE school='x'"),
        ("school", "Total enrollment?", "", "SELECT SUM(enrollment) FROM frpm"),
        ("school", "Broken gold", "", "SELECT nope FROM frpm"),
    ]
    raw = [
        {"question_id": i, "db_id": db, "question": q, "evidence": e, "SQL": s, "difficulty": "simple"}
        for i, (db, q, e, s) in enumerate(qs)
    ]
    (root / "dev.json").write_text(json.dumps(raw))
    return root
