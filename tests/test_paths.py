"""Tests for Pursuit path selection."""

from __future__ import annotations

import pytest

from video_benchmark.paths import ALL_PATHS, DEFAULT_PATHS, apply_skip_flags, parse_paths


def test_default_paths_are_gemini_compare():
    assert parse_paths(None) == set(DEFAULT_PATHS)
    assert parse_paths('') == set(DEFAULT_PATHS)
    assert DEFAULT_PATHS == {'1', '2'}


def test_parse_paths_subset():
    assert parse_paths('3') == {'3'}
    assert parse_paths('1,2,3') == {'1', '2', '3'}
    assert parse_paths('1, 5') == {'1', '5'}


def test_parse_paths_rejects_unknown():
    with pytest.raises(ValueError, match='Unknown paths'):
        parse_paths('1,9')


def test_parse_paths_custom_allowed():
    allowed = frozenset({'1', '2', '3', '5'})
    assert parse_paths(None, allowed=allowed, default=frozenset({'1', '2'})) == {'1', '2'}
    with pytest.raises(ValueError, match='Unknown paths'):
        parse_paths('4', allowed=frozenset({'1', '2', '3', '5'}))


def test_apply_skip_flags():
    paths = set(ALL_PATHS)
    assert apply_skip_flags(paths, skip_oss=True, skip_fal=True, skip_nova=True) == {
        '1',
        '2',
    }
