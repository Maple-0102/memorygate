from memorygate.data import load_bird
from memorygate.llm import FakeClient, Pricing, UsageMeter
from memorygate.memory import ExperienceBank
from memorygate.runner import run_condition


def test_retrieval_is_same_db_and_excludes_self(bird_dir):
    tasks = load_bird(bird_dir)
    bank = ExperienceBank.from_tasks(tasks)
    q = next(t for t in tasks if t.question == "Total amount in dollars?")
    got = bank.retrieve(q, 5)
    assert got and all(e.db_id == "shop" for e in got)
    assert q.qid not in [e.qid for e in got]


def test_bank_drops_ungradable_and_keeps_no_hint_text(bird_dir):
    tasks = load_bird(bird_dir)
    bank = ExperienceBank.from_tasks(tasks, {tasks[-1].qid: {"gold_error": "x"}})
    assert tasks[-1].qid not in bank.items
    assert all("stored in cents" not in e.render() for e in bank.items.values())  # hints are not stored


def test_render_shows_failed_attempt(bird_dir):
    t = load_bird(bird_dir)[1]
    bank = ExperienceBank.from_tasks([t], {t.qid: {"pred_sql": "SELECT SUM(amount_cents) FROM orders", "correct": False}})
    text = bank.items[t.qid].render()
    assert "Earlier wrong attempt" in text and "Correct SQL" in text


def test_shuffled_is_seeded_and_same_db(bird_dir):
    tasks = load_bird(bird_dir)
    bank = ExperienceBank.from_tasks(tasks)
    a = bank.random_same_db(tasks[0], 2, seed=1)
    assert a == bank.random_same_db(tasks[0], 2, seed=1)
    assert all(e.db_id == tasks[0].db_id and e.qid != tasks[0].qid for e in a)


def test_runner_records_memory_ids(bird_dir, tmp_path):
    tasks = load_bird(bird_dir)
    bank = ExperienceBank.from_tasks(tasks[:3])
    s = run_condition(tasks[3:4], "raw_retrieval", UsageMeter(FakeClient(), Pricing(0, 0, 0)), bird_dir, tmp_path / "r",
                      retrieve=lambda t: bank.retrieve(t, 2))
    import json
    rec = json.loads((tmp_path / "r" / "trajectories.jsonl").read_text())
    assert rec["memory_ids"] and len(rec["hints"]) == len(rec["memory_ids"]) and s["n"] == 1
