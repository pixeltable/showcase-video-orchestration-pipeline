"""One accounting policy: a missing cost makes the total unknown, but keeps known spend."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CostTotals:
    total: float | None
    known: float
    unknown: int


def cost_totals(values: Iterable[float | None]) -> CostTotals:
    known = 0.0
    unknown = 0
    for value in values:
        if value is None:
            unknown += 1
        else:
            known += value
    return CostTotals(total=None if unknown else known, known=known, unknown=unknown)
