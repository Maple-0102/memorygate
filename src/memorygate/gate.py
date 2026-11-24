"""Regression gate: compare candidate vs current memory on the validation split, item by item.

fixed  = items the current version got wrong and the candidate got right
broken = items the current version got right and the candidate got wrong
The paired accuracy difference d = (fixed - broken) / n has standard error
se = sqrt(((fixed + broken)/n - d^2) / n). With z = d / se:

  default_accept : accept unless there is evidence of harm   (reject if z < -z_crit)
  default_reject : reject unless there is evidence of benefit (accept if z >  z_crit)

`effect` labels the comparison itself: improved / worse / unclear (within noise).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt

POLICIES = ("default_accept", "default_reject")


@dataclass
class GateDecision:
    accept: bool
    policy: str
    n: int
    fixed: int
    broken: int
    diff: float
    se: float
    z: float
    effect: str

    def to_dict(self) -> dict:
        return asdict(self)


def decide(fixed: int, broken: int, n: int, policy: str, z_crit: float = 1.645) -> GateDecision:
    if policy not in POLICIES:
        raise ValueError(policy)
    if n <= 0:
        return GateDecision(policy == "default_accept", policy, 0, fixed, broken, 0.0, 0.0, 0.0, "unclear")
    d = (fixed - broken) / n
    var = max((fixed + broken) / n - d * d, 0.0)
    se = sqrt(var / n)
    z = d / se if se > 0 else 0.0
    effect = "improved" if z > z_crit else "worse" if z < -z_crit else "unclear"
    accept = (z >= -z_crit) if policy == "default_accept" else (z > z_crit)
    return GateDecision(accept, policy, n, fixed, broken, round(d, 4), round(se, 4), round(z, 3), effect)
