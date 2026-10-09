"""Intervals and paired tests."""

from __future__ import annotations

import math

import pytest

from video_benchmark.stats import (
    cluster_bootstrap,
    difference_of,
    mcnemar_exact,
    mean_of,
    paired_cluster_test,
    wilson_interval,
)


def test_wilson_interval():
    lo, hi = wilson_interval(24, 30)
    assert lo == pytest.approx(0.627, abs=1e-3) and hi == pytest.approx(0.905, abs=1e-3)
    assert wilson_interval(0, 10)[0] == 0.0
    assert all(math.isnan(v) for v in wilson_interval(0, 0))


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    # 8 vs 2 discordant pairs: two-sided exact binomial p = 0.109
    assert mcnemar_exact(8, 2) == pytest.approx(0.1094, abs=1e-4)
    assert mcnemar_exact(2, 8) == mcnemar_exact(8, 2)


def test_cluster_bootstrap_resamples_videos():
    # Two videos: one always right, one always wrong; questions within a video move together.
    rows = [{'video_id': 'a', 'ok': True}] * 3 + [{'video_id': 'b', 'ok': False}] * 3
    lo, hi = cluster_bootstrap(rows, 'video_id', mean_of('ok'), n_boot=2000, seed=1)
    assert lo == 0.0 and hi == 1.0
    same = cluster_bootstrap(
        rows, 'video_id', difference_of(mean_of('ok'), mean_of('ok')), n_boot=200
    )
    assert same == (0.0, 0.0)


def test_paired_cluster_test_exchanges_whole_videos():
    # Three correct questions in one video are one exchangeable unit, not three.
    rows = [{'video_id': 'a', 'a': True, 'b': False}] * 3
    assert paired_cluster_test(rows, 'video_id', 'a', 'b') == 1.0
    rows += [{'video_id': 'b', 'a': True, 'b': None}] * 3
    assert paired_cluster_test(rows, 'video_id', 'a', 'b') == 0.5
    assert paired_cluster_test(rows, 'video_id', 'b', 'a') == 0.5
    assert paired_cluster_test([], 'video_id', 'a', 'b') == 1.0
