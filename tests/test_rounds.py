import json
import sqlite3

import pytest

from memorygate.consolidate import _parse, consolidate_scope, prune
from memorygate.data import load_bird
from memorygate.gate import decide
from memorygate.llm import FakeClient, Pricing, UsageMeter
from memorygate.memstore import MemoryStore, diff
from memorygate.rounds import chunk, dev_streams, run_group
from memorygate.splits import make_split, write_split

FREE = Pricing(0, 0, 0)


# ---------------- gate ----------------

def test_gate_policies():
    # clear improvement: both accept
    assert decide(30, 2, 300, "default_accept").accept and decide(30, 2, 300, "default_reject").accept
    # clear harm: both reject
    assert not decide(2, 30, 300, "default_accept").accept and not decide(2, 30, 300, "default_reject").accept
    # within noise: the policies disagree
    g_a, g_r = decide(6, 4, 300, "default_accept"), decide(6, 4, 300, "default_reject")
    assert g_a.accept and not g_r.accept and g_a.effect == "unclear"
    assert decide(0, 0, 300, "default_reject").accept is False
    with pytest.raises(ValueError):
        decide(1, 1, 10, "nope")


# ---------------- memory store ----------------

def _task(q, db="shop"):
    from memorygate.data import Task
    return Task("T9999", db, q, "", "SELECT 1", "simple")


def test_store_scope_budget_and_persistence(tmp_path):
    m = MemoryStore()
    a = m.add("db:shop", "amount_cents is in cents; divide by 100 for dollars", ["T1"], 0)
    m.add("db:school", "amount means enrollment here", ["T2"], 0)
    g = m.add("global", "use CAST(x AS REAL) before dividing amount columns", ["T3"], 0)
    got = [e.id for e in m.retrieve(_task("total amount in dollars"), 5, 10_000)]
    assert a.id in got and g.id in got and len(got) == 2  # other db's entry is filtered out by scope
    assert len(m.retrieve(_task("total amount in dollars"), 5, 60)) == 1  # budget keeps at least one, then stops
    m.record_outcome([a.id], True)
    m.record_outcome([a.id], False)
    m.save(tmp_path / "m.json")
    m2 = MemoryStore.load(tmp_path / "m.json")
    assert (m2.entries[a.id].uses, m2.entries[a.id].wins, m2.entries[a.id].losses) == (2, 1, 1)
    assert m2.new_id() == "L0004"


def test_prune_and_diff():
    m = MemoryStore()
    bad = m.add("db:shop", "bad rule", [], 0)
    ok = m.add("db:shop", "good rule", [], 0)
    bad.uses, bad.wins, bad.losses = 8, 1, 7
    ok.uses, ok.wins, ok.losses = 8, 4, 4
    new = m.copy()
    assert prune(new, 6, 2.0) == [bad.id]
    d = diff(m, new)
    assert d["removed"][0]["id"] == bad.id and d["removed"][0]["status"] == "retired" and m.entries[bad.id].status == "active"


def test_parse_tolerates_wrapping():
    assert _parse('```json\n{"lessons": [{"text": "x"}]}\n```', "lessons") == [{"text": "x"}]
    assert _parse("not json", "lessons") is None


def test_consolidate_merges_keeps_and_refuses_invented():
    m = MemoryStore()
    a = m.add("db:shop", "amount is cents", ["T1"], 0)
    b = m.add("db:shop", "orders.amount_cents / 100 gives dollars", ["T2"], 0)
    c = m.add("db:shop", "city codes are single letters", ["T3"], 0)
    a.uses, a.wins = 3, 2
    resp = json.dumps({"entries": [
        {"text": "amount_cents is in cents: divide by 100 for dollars", "sources": [a.id, b.id, "N1"]},
        {"text": c.text, "sources": [c.id]},
        {"text": "invented fact", "sources": ["L9999"]},
    ]})
    meter = UsageMeter(FakeClient(lambda p: resp), FREE)
    log = consolidate_scope(meter, m, "db:shop", [{"text": "cents!", "evidence_tasks": ["T4"]}], 1, 25)
    act = m.active("db:shop")
    assert {e.text for e in act} == {"amount_cents is in cents: divide by 100 for dollars", c.text}
    merged = next(e for e in act if e.merged_from)
    assert set(merged.evidence_tasks) == {"T1", "T2", "T4"} and merged.uses == 3 and merged.wins == 2
    assert m.entries[a.id].status == "retired" and log["kept"] == 1


# ---------------- full round loop (offline) ----------------

@pytest.fixture
def big(tmp_path):
    """60 tasks over two dbs, and a config pointing at them."""
    root = tmp_path / "bird"
    raw = []
    for db in ("shop", "school"):
        d = root / "dev_databases" / db
        d.mkdir(parents=True)
        conn = sqlite3.connect(d / f"{db}.sqlite")
        conn.execute("CREATE TABLE t (v INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(50)])
        conn.commit()
        conn.close()
        for i in range(30):
            raw.append({"question_id": len(raw), "db_id": db, "question": f"count values above {i} in {db}",
                        "evidence": "", "SQL": f"SELECT COUNT(*) FROM t WHERE v > {i}", "difficulty": "simple"})
    (root / "dev.json").write_text(json.dumps(raw))
    cfg = {
        "model": {"provider": "fake", "name": "fake"},
        "pricing": {"input": 0, "cached_input": 0, "output": 0},
        "data": {"bird_dir": str(root), "split_dir": str(tmp_path / "splits"), "sealed_dir": str(tmp_path / "sealed"),
                 "seed": 1, "ratios": {"learn": 0.6, "val": 0.2, "test": 0.2}},
        "exec": {"timeout_s": 5, "max_rows": 1000},
        "rounds": {"n_rounds": 3, "dev_eval_frac": 0.3, "dev_eval_seed": 7, "eval_every": 1, "k": 5, "char_budget": 1500,
                   "distill_max_items": 15, "distill_max_lessons": 5, "cap_per_db": 25, "cap_global": 10,
                   "prune_min_uses": 6, "prune_loss_ratio": 2.0, "gate_z": 1.645},
    }
    tasks = load_bird(root)
    write_split(make_split(tasks, 1, cfg["data"]["ratios"]), 1, cfg["data"]["split_dir"], cfg["data"]["sealed_dir"], "x")
    gold = {t.question: t.gold_sql for t in tasks}

    def respond(p):
        if '"lessons"' in p:
            ids = [w.strip("[]") for w in p.split() if w.startswith("[T")]
            return json.dumps({"lessons": [{"text": f"rule from {ids[0]}: values are integers 0-49", "scope": "db",
                                            "evidence_tasks": ids[:1]}]})
        if '"entries"' in p:
            return "{}"  # unparseable consolidation -> fallback path
        q = next(q for q in gold if f"### Question\n{q}" in p)
        # wrong unless a memory note is present and the threshold is even
        n = int(q.split()[3])
        return f"```sql\n{gold[q] if ('Notes' in p and n % 2 == 0) else 'SELECT -1'}\n```"

    return cfg, FakeClient(respond)


def test_streams_are_disjoint_and_test_untouched(big):
    cfg, _ = big
    stream, ev, val, _ = dev_streams(cfg)
    s, e, v = {t.qid for t in stream}, {t.qid for t in ev}, {t.qid for t in val}
    assert not (s & e) and not (s & v) and not (e & v)
    assert sum(len(b) for b in chunk(stream, 0, 3)) == len(stream)
    assert chunk(stream, 0, 3) != chunk(stream, 1, 3)


@pytest.mark.parametrize("group", ["no_memory", "raw", "consolidate", "gate_accept", "gate_reject"])
def test_round_loop_runs_and_resumes(big, tmp_path, group):
    cfg, fake = big
    out = tmp_path / "runs" / group
    meter = UsageMeter(fake, FREE)
    hist = run_group(cfg, group, meter, out, order_seed=0, workers=2)
    assert len(hist) == 3 and all("eval_acc" in h for h in hist)
    assert (out / "round_02" / "report.md").exists() and (out / "round_02" / "memory.json").exists()
    calls = meter.calls
    again = run_group(cfg, group, meter, out, order_seed=0, workers=2)
    assert meter.calls == calls and len(again) == 3  # finished rounds are not redone
    if group == "gate_reject":
        assert all(h["gate"]["accept"] == (h["gate"]["z"] > 1.645) for h in hist)
    if group in ("consolidate", "gate_accept"):
        assert hist[-1]["memory_size"] > 0


def test_harmful_update_is_blocked_and_quarantined(big, tmp_path):
    cfg, fake = big
    helpful = fake.responder

    def respond(p):  # any memory note makes the answer wrong
        out = helpful(p)
        if "### Question" in p and '"lessons"' not in p and '"entries"' not in p:
            q = p.split("### Question\n")[1].split("\n")[0]
            gold = next(t.gold_sql for t in load_bird(cfg["data"]["bird_dir"]) if t.question == q)
            n = int(q.split()[3])
            ok = "Notes" not in p and n % 2 == 0  # odd ones fail (so there is something to distill)
            return f"```sql\n{gold if ok else 'SELECT -1'}\n```"
        return out

    meter = UsageMeter(FakeClient(respond), FREE)
    hist = run_group(cfg, "gate_accept", meter, tmp_path / "harm", order_seed=0, workers=2)
    assert all(not h["gate"]["accept"] and h["gate"]["effect"] == "worse" for h in hist)
    mem = MemoryStore.load(tmp_path / "harm" / "round_02" / "memory.json")
    assert not mem.active() and any(e.status == "quarantined" for e in mem.entries.values())
    assert "REJECTED" in (tmp_path / "harm" / "round_00" / "report.md").read_text()


def test_posthoc_labels_and_scorecard(big, tmp_path):
    from memorygate.posthoc import gate_scorecard, label_run, rounds_summary
    cfg, fake = big
    runs = tmp_path / "runs"
    for g in ("gate_reject", "consolidate"):
        run_group(cfg, g, UsageMeter(fake, FREE), runs / f"o0_{g}", order_seed=0, workers=2)
    meter = UsageMeter(fake, FREE)
    rows = label_run(cfg, runs / "o0_gate_reject", meter, workers=2)
    assert len(rows) == 3 and all(r["label"] in ("improved", "worse", "unclear") for r in rows)
    calls = meter.calls
    label_run(cfg, runs / "o0_gate_reject", meter, workers=2)
    assert meter.calls == calls  # cached by memory content
    rows_c = label_run(cfg, runs / "o0_consolidate", UsageMeter(fake, FREE), workers=2)
    assert all(r["accepted"] for r in rows_c)
    s = gate_scorecard([{"label": "worse", "accepted": True}, {"label": "worse", "accepted": False},
                        {"label": "improved", "accepted": False}, {"label": "unclear", "accepted": True}])
    assert (s["harmful"], s["harmful_accepted"], s["beneficial_rejected"], s["unclear"]) == (2, 1, 1, 1)
    text = rounds_summary(runs, tmp_path / "r.md")
    assert "o0_gate_reject" in text and "| 2 |" in text


def test_harm_injection_replays_updates(big, tmp_path):
    from memorygate.harm import inject_run, injection_summary
    from memorygate.posthoc import label_run
    cfg, fake = big
    runs = tmp_path / "runs"
    run = runs / "o0_gate_accept"
    run_group(cfg, "gate_accept", UsageMeter(fake, FREE), run, order_seed=0, workers=2)
    label_run(cfg, run, UsageMeter(fake, FREE), workers=2)
    helpful = fake.responder

    def respond(p):
        if '"notes"' in p and "Rewrite EACH note" in p:
            ids = [w.strip("[]") for w in p.split() if w.startswith("[L")]
            return json.dumps({"notes": [{"id": i, "text": "POISON values are text"} for i in ids]})
        if "POISON" in p:  # a corrupted note in the context makes the answer wrong
            return "```sql\nSELECT -1\n```"
        return helpful(p)

    meter = UsageMeter(FakeClient(respond), FREE)
    rows = inject_run(cfg, run, 1.0, meter, workers=2)
    assert rows and all(r["n_corrupted"] >= 1 for r in rows)
    assert all(r["eval_candidate"] <= r["eval_before"] for r in rows)
    assert any(r["label"] == "worse" and not r["accept_default_reject"] for r in rows)
    bad = MemoryStore.load(run / "round_00" / "inject_100" / "candidate.json")
    assert all(e.text == "POISON values are text" for e in bad.active())
    calls = meter.calls
    inject_run(cfg, run, 1.0, meter, workers=2)
    assert meter.calls == calls  # corruption and evaluations are cached
    assert "| 1.00 |" in injection_summary(runs)
