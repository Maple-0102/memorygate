from memorygate.data import Task
from memorygate.memory import Experience
from memorygate.memstore import Entry, MemoryStore
from memorygate.mixed import retriever
from memorygate.rounds import RawMemory


def _task():
    return Task(qid="Q1", db_id="db", question="total sales by region", gold_sql="", evidence="", difficulty="simple")


def test_mixed_takes_three_raw_then_rules_that_fit():
    exps = [Experience(f"E{i}", "db", f"sales by region {i}", "SELECT " + "x" * 300, None, None, True) for i in range(5)]
    raw = RawMemory(exps)
    ents = [Entry(id=f"R{i}", scope="db:db", text=f"sales region rule {i} " + "y" * n)
            for i, n in enumerate((100, 600, 100, 100))]
    rules = MemoryStore(ents)
    got = retriever("mixed", raw, rules, 5, 1500)(_task())
    kinds = [hasattr(g, "scope") for g in got]
    assert kinds[:3] == [False, False, False]
    assert sum(kinds) <= 2
    assert sum(len(g.render()) for g in got) <= 1500
    assert all(len(g.render()) < 600 for g in got if hasattr(g, "scope"))  # the long rule did not fit
