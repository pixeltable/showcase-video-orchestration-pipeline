"""Uncertainty for small evaluation sets.

Video-MME asks several questions per video. Intervals resample whole videos; paired tests
exchange the two paths' outcomes for a whole video together. Question-level McNemar is kept
as a descriptive diagnostic whose independence assumption does not hold for this sample.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(a_only: int, b_only: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts (A right & B wrong, and
    vice versa)."""
    n = a_only + b_only
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_cluster_test(
    rows: Sequence[dict[str, Any]], cluster_key: str, a_key: str, b_key: str
) -> float:
    """Exact two-sided paired label-exchange test at the video level.

    Count correct outcomes (a missing outcome is wrong) within each video. Under the null,
    each video's path labels can be exchanged together; enumerate the distribution of the
    signed count differences with integer dynamic programming. This preserves within-video
    dependence. The exchangeability assumption and exploratory comparisons should be reported.
    """
    differences: dict[Any, int] = defaultdict(int)
    for row in rows:
        differences[row[cluster_key]] += int(bool(row.get(a_key))) - int(bool(row.get(b_key)))
    observed = abs(sum(differences.values()))
    distribution = {0: 1}
    for delta in differences.values():
        if delta == 0:
            continue
        updated: dict[int, int] = defaultdict(int)
        for total, ways in distribution.items():
            updated[total + delta] += ways
            updated[total - delta] += ways
        distribution = updated
    extreme = sum(ways for total, ways in distribution.items() if abs(total) >= observed)
    return extreme / sum(distribution.values())


def cluster_bootstrap(
    rows: Sequence[dict[str, Any]],
    cluster_key: str,
    statistic: Callable[[list[dict[str, Any]]], float],
    *,
    n_boot: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """95% percentile interval of `statistic`, resampling clusters (videos) with replacement."""
    clusters: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        clusters[row[cluster_key]].append(row)
    groups = list(clusters.values())
    if not groups:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_boot):
        picks = rng.integers(0, len(groups), size=len(groups))
        resampled = [row for i in picks for row in groups[i]]
        value = statistic(resampled)
        if not math.isnan(value):
            samples.append(value)
    if not samples:
        return (math.nan, math.nan)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return (float(lo), float(hi))


def mean_of(key: str) -> Callable[[list[dict[str, Any]]], float]:
    """Statistic: mean of `key` over rows where it is present (bools count as 0/1)."""

    def statistic(rows: list[dict[str, Any]]) -> float:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return sum(values) / len(values) if values else math.nan

    return statistic


def difference_of(
    a: Callable[[list[dict[str, Any]]], float], b: Callable[[list[dict[str, Any]]], float]
) -> Callable[[list[dict[str, Any]]], float]:
    return lambda rows: a(rows) - b(rows)
