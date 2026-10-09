"""Path selection."""

from __future__ import annotations

import pytest

from video_benchmark.config import load_config
from video_benchmark.paths import ALL_PATHS, DEFAULT_PATHS, apply_skip_flags, parse_paths
from video_benchmark.schema import plan_paths


def test_default_is_native_vs_orchestrated():
    assert parse_paths(None) == parse_paths('') == set(DEFAULT_PATHS) == {'1', '2'}


def test_parse_paths_subset_and_case():
    assert parse_paths('1, 1l,2') == {'1', '1L', '2'}
    assert parse_paths('3') == {'3'}


def test_parse_paths_rejects_unknown():
    with pytest.raises(ValueError, match='Unknown paths'):
        parse_paths('1,9')
    with pytest.raises(ValueError, match='Unknown paths'):
        parse_paths('4', allowed=frozenset({'1', '2'}))


def test_skip_flags():
    assert apply_skip_flags(set(ALL_PATHS), skip_oss=True, skip_fal=True, skip_nova=True) == {
        '1',
        '1L',
        '2',
    }


def test_plan_needs_credentials_for_fal_and_nova(monkeypatch):
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)
    for key in ('ENABLE_FAL', 'ENABLE_NOVA', 'FAL_KEY', 'FAL_API_KEY', 'AWS_ACCESS_KEY_ID'):
        monkeypatch.delenv(key, raising=False)
    plan = plan_paths(load_config(), set(ALL_PATHS))
    assert plan.enabled() == ['1', '1L', '2', '3']
    assert plan.modular and plan.gemini_asr
