from memorygate.data import db_path
from memorygate.grader import compare, grade
from memorygate.sqlexec import execute


def test_compare_ignores_order_and_duplicates_but_strict_does_not():
    assert compare([(1,), (2,)], [(2,), (1,)]) == (True, True)
    assert compare([(1,), (1,)], [(1,)]) == (True, False)
    assert compare([(1,)], [(2,)]) == (False, False)


def test_equivalent_sql_is_correct(bird_dir):
    p = db_path(bird_dir, "shop")
    g = grade(p, "SELECT count(id) FROM orders", "SELECT COUNT(*) FROM orders")
    assert g.correct and g.strict and g.pred_error is None


def test_wrong_value_is_incorrect(bird_dir):
    p = db_path(bird_dir, "shop")
    g = grade(p, "SELECT SUM(amount_cents) FROM orders", "SELECT SUM(amount_cents) / 100.0 FROM orders")
    assert not g.correct and g.pred_error is None


def test_pred_error_and_empty_sql(bird_dir):
    p = db_path(bird_dir, "shop")
    assert "no such column" in grade(p, "SELECT nope FROM orders", "SELECT 1").pred_error
    assert grade(p, None, "SELECT 1").pred_error == "no SQL produced"


def test_gold_error_is_ungradable_not_wrong(bird_dir):
    g = grade(db_path(bird_dir, "school"), "SELECT 1", "SELECT nope FROM frpm")
    assert g.gold_error and g.pred_error is None and not g.correct


def test_database_is_read_only(bird_dir):
    p = db_path(bird_dir, "shop")
    r = execute(p, "DELETE FROM orders")
    assert not r.ok
    assert execute(p, "SELECT COUNT(*) FROM orders").rows == [(3,)]


def test_timeout(bird_dir):
    slow = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"
    r = execute(db_path(bird_dir, "shop"), slow, timeout_s=0.3)
    assert not r.ok and r.error == "timeout"


def test_row_cap(bird_dir):
    r = execute(db_path(bird_dir, "shop"), "SELECT * FROM orders", max_rows=2)
    assert r.ok and r.truncated and len(r.rows) == 2
