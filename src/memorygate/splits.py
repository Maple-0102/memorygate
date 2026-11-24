"""Per-database learn / val / test split with a sealed test set.

`learn` and `val` ids go to <split_dir>/split_seed<seed>.json and may be used freely.
`test` ids go to <sealed_dir>/test_seed<seed>.json; the public split file records only
their count and SHA-256. `load_split("test")` refuses unless explicitly unsealed, so
week-1 design work cannot touch the test set by accident.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from .data import Task

PUBLIC = ("learn", "val")


class SealedSplitError(PermissionError):
    pass


def _digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def make_split(tasks: list[Task], seed: int, ratios: dict[str, float]) -> dict[str, list[str]]:
    assert abs(sum(ratios.values()) - 1.0) < 1e-9, ratios
    by_db: dict[str, list[str]] = defaultdict(list)
    for t in tasks:
        by_db[t.db_id].append(t.qid)
    out = {"learn": [], "val": [], "test": []}
    for db in sorted(by_db):
        ids = sorted(by_db[db])
        random.Random(f"{seed}:{db}").shuffle(ids)
        n = len(ids)
        n_learn = round(n * ratios["learn"])
        n_val = round(n * ratios["val"])
        out["learn"] += ids[:n_learn]
        out["val"] += ids[n_learn : n_learn + n_val]
        out["test"] += ids[n_learn + n_val :]
    return out


def write_split(split: dict[str, list[str]], seed: int, split_dir: str | Path, sealed_dir: str | Path, source_sha256: str) -> Path:
    split_dir, sealed_dir = Path(split_dir), Path(sealed_dir)
    split_dir.mkdir(parents=True, exist_ok=True)
    sealed_dir.mkdir(parents=True, exist_ok=True)
    test_path = sealed_dir / f"test_seed{seed}.json"
    pub_path = split_dir / f"split_seed{seed}.json"
    if pub_path.exists() or test_path.exists():
        raise FileExistsError(f"split for seed {seed} already exists; splits are frozen once written")
    test_path.write_text(json.dumps(sorted(split["test"]), indent=0))
    pub = {
        "seed": seed,
        "source_sha256": source_sha256,
        "learn": sorted(split["learn"]),
        "val": sorted(split["val"]),
        "test_count": len(split["test"]),
        "test_sha256": _digest(split["test"]),
    }
    pub_path.write_text(json.dumps(pub, indent=1))
    return pub_path


def load_split(name: str, seed: int, split_dir: str | Path, sealed_dir: str | Path, unseal: bool = False) -> list[str]:
    pub = json.loads((Path(split_dir) / f"split_seed{seed}.json").read_text())
    if name in PUBLIC:
        return pub[name]
    if name != "test":
        raise ValueError(name)
    if not unseal:
        raise SealedSplitError("test split is sealed until the design is frozen (pass unseal=True deliberately)")
    ids = json.loads((Path(sealed_dir) / f"test_seed{seed}.json").read_text())
    if _digest(ids) != pub["test_sha256"]:
        raise ValueError("sealed test ids do not match the recorded hash")
    return ids
