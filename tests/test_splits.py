import json

import pytest

from memorygate.data import load_bird
from memorygate.splits import SealedSplitError, load_split, make_split, write_split

RATIOS = {"learn": 0.5, "val": 0.2, "test": 0.3}


def test_split_is_disjoint_complete_and_per_db(bird_dir):
    tasks = load_bird(bird_dir)
    s = make_split(tasks, 7, RATIOS)
    all_ids = s["learn"] + s["val"] + s["test"]
    assert sorted(all_ids) == sorted(t.qid for t in tasks)
    assert len(set(all_ids)) == len(all_ids)
    db_of = {t.qid: t.db_id for t in tasks}
    assert {db_of[q] for q in s["learn"]} == {"shop", "school"}


def test_split_is_deterministic_and_seed_sensitive(bird_dir):
    tasks = load_bird(bird_dir)
    assert make_split(tasks, 7, RATIOS) == make_split(list(reversed(tasks)), 7, RATIOS)
    assert any(make_split(tasks, 7, RATIOS) != make_split(tasks, s, RATIOS) for s in range(8, 20))


def test_test_split_is_sealed(bird_dir, tmp_path):
    s = make_split(load_bird(bird_dir), 7, RATIOS)
    pub = write_split(s, 7, tmp_path / "splits", tmp_path / "sealed", "abc")
    assert "test" not in json.loads(pub.read_text())
    assert load_split("learn", 7, tmp_path / "splits", tmp_path / "sealed") == sorted(s["learn"])
    with pytest.raises(SealedSplitError):
        load_split("test", 7, tmp_path / "splits", tmp_path / "sealed")
    assert load_split("test", 7, tmp_path / "splits", tmp_path / "sealed", unseal=True) == sorted(s["test"])


def test_split_is_frozen_and_tamper_checked(bird_dir, tmp_path):
    s = make_split(load_bird(bird_dir), 7, RATIOS)
    write_split(s, 7, tmp_path / "splits", tmp_path / "sealed", "abc")
    with pytest.raises(FileExistsError):
        write_split(s, 7, tmp_path / "splits", tmp_path / "sealed", "abc")
    (tmp_path / "sealed" / "test_seed7.json").write_text(json.dumps(["T9999"]))
    with pytest.raises(ValueError):
        load_split("test", 7, tmp_path / "splits", tmp_path / "sealed", unseal=True)
