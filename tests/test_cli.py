"""Fail invalid requests before downloads, catalog resets, or paid preparation."""

from __future__ import annotations

import sys

from video_benchmark import cli
from video_benchmark.videomme import cli as vm_cli


def test_missing_video_is_validated_before_reset(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['run-benchmark', '--video', str(tmp_path / 'missing.mp4'),
                                      '--reset', '--paths', '1'])
    resets = []
    monkeypatch.setattr(cli, 'reset_catalog', lambda: resets.append(True))
    assert cli.main() == 1 and resets == []


def test_invalid_repeat_count_never_downloads(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run-benchmark', '--repeats', '0'])
    monkeypatch.setattr(cli, 'ensure_sample_video', lambda *args: (_ for _ in ()).throw(
        AssertionError('must not download')
    ))
    assert cli.main() == 1


def test_videomme_credentials_are_checked_before_downloading(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run-videomme', '--paths', '1'])
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(vm_cli, 'prepare_sample', lambda **kwargs: (_ for _ in ()).throw(
        AssertionError('must not download')
    ))
    assert vm_cli.main() == 1
