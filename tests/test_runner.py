import json

import pytest

from memorygate.data import load_bird
from memorygate.llm import BudgetExceeded, Completion, FakeClient, Pricing, UsageMeter
from memorygate.runner import order_tasks, paired, run_condition

FREE = Pricing(0, 0, 0)


def gold_oracle(tasks):
    """Fake model that answers with the gold SQL only when the hint is in the prompt."""
    by_q = {t.question: t for t in tasks}

    def respond(prompt):
        t = next(t for q, t in by_q.items() if q in prompt)
        if t.evidence and t.evidence not in prompt:
            return "```sql\nSELECT -1\n```"
        return f"```sql\n{t.gold_sql}\n```"

    return respond


def test_evidence_beats_no_memory_and_paired_counts(bird_dir, tmp_path):
    tasks = load_bird(bird_dir)
    fake = FakeClient(gold_oracle(tasks))
    a = run_condition(tasks, "no_memory", UsageMeter(fake, FREE), bird_dir, tmp_path / "a")
    b = run_condition(tasks, "evidence", UsageMeter(fake, FREE), bird_dir, tmp_path / "b")
    assert a["n_gold_error"] == 1 and a["n_graded"] == 7
    assert a["accuracy"] == round(5 / 7, 4) and b["accuracy"] == 1.0
    p = paired(tmp_path / "a", tmp_path / "b")
    assert (p["fixed"], p["broken"], p["n_shared"]) == (2, 0, 7)


def test_resume_skips_done_items(bird_dir, tmp_path):
    tasks = load_bird(bird_dir)
    meter = UsageMeter(FakeClient(gold_oracle(tasks)), FREE)
    run_condition(tasks[:3], "no_memory", meter, bird_dir, tmp_path / "r")
    run_condition(tasks, "no_memory", meter, bird_dir, tmp_path / "r")
    assert meter.calls == len(tasks)
    lines = (tmp_path / "r" / "trajectories.jsonl").read_text().splitlines()
    assert len(lines) == len(tasks)


def test_budget_cap_stops_cleanly(bird_dir, tmp_path):
    tasks = load_bird(bird_dir)
    meter = UsageMeter(FakeClient(gold_oracle(tasks)), FREE, max_calls=3)
    s = run_condition(tasks, "no_memory", meter, bird_dir, tmp_path / "r")
    assert s["n"] == 3 and "call cap" in s["stopped"]


def test_cost_and_usage_log(tmp_path):
    class Fixed:
        model = "m"

        def generate(self, prompt, system=None, **kw):
            return Completion("x", input_tokens=1_000_000, cached_tokens=400_000, output_tokens=100_000, thinking_tokens=100_000)

    log = tmp_path / "usage.jsonl"
    m = UsageMeter(Fixed(), Pricing(input=1.0, cached_input=0.1, output=2.0), log_path=log, max_usd=0.5)
    m.generate("p", tag="t")
    # 0.6M*1.0 + 0.4M*0.1 + 0.2M*2.0 = 0.6 + 0.04 + 0.4 = 1.04 USD
    assert m.usd == pytest.approx(1.04)
    rec = json.loads(log.read_text())
    assert rec["tag"] == "t" and "text" not in rec
    with pytest.raises(BudgetExceeded):
        m.generate("p")


def test_order_is_seeded_and_input_independent(bird_dir):
    tasks = load_bird(bird_dir)
    assert order_tasks(tasks, 1) == order_tasks(list(reversed(tasks)), 1)
    assert order_tasks(tasks, 1) != order_tasks(tasks, 2)


def test_parallel_run_matches_serial_and_respects_cap(bird_dir, tmp_path):
    tasks = load_bird(bird_dir)
    fake = FakeClient(gold_oracle(tasks))
    a = run_condition(tasks, "evidence", UsageMeter(fake, FREE), bird_dir, tmp_path / "s", workers=1)
    b = run_condition(tasks, "evidence", UsageMeter(fake, FREE), bird_dir, tmp_path / "p", workers=4)
    assert a["accuracy"] == b["accuracy"] and a["n"] == b["n"]
    m = UsageMeter(fake, FREE, max_calls=5)
    c = run_condition(tasks, "no_memory", m, bird_dir, tmp_path / "c", workers=4)
    assert m.calls == 5 and c["n"] == 5 and c["stopped"]


def test_mcnemar_and_tokens():
    from memorygate.analysis import mcnemar_p, sql_tokens
    assert mcnemar_p(0, 0) == 1.0
    assert mcnemar_p(10, 0) < 0.01 and mcnemar_p(5, 5) == 1.0
    assert sql_tokens("SELECT T1.Free_Meal FROM frpm AS T1 WHERE x = 'A'") == {"free_meal", "frpm", "x", "'a'"}


def test_retry_on_timeout_and_429(monkeypatch):
    import memorygate.llm as L
    monkeypatch.setattr(L.time, "sleep", lambda s: None)

    class ReadTimeout(Exception):
        pass

    class Http(Exception):
        def __init__(self, code):
            self.code = code

    seq = [ReadTimeout(), Http(429), "ok"]

    def fn():
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    assert L._with_retry(fn) == "ok"
    with pytest.raises(Http):
        L._with_retry(lambda: (_ for _ in ()).throw(Http(400)))
