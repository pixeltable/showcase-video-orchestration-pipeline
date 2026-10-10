"""Fail invalid requests before downloads, catalog resets, or paid preparation."""

from __future__ import annotations

import sys
from contextlib import contextmanager

import pytest

from video_benchmark import cli
from video_benchmark.videomme import cli as vm_cli


def test_missing_video_is_validated_before_reset(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        'argv',
        ['run-benchmark', '--video', str(tmp_path / 'missing.mp4'), '--reset', '--paths', '1'],
    )
    resets = []
    monkeypatch.setattr(cli, 'reset_catalog', lambda: resets.append(True))
    assert cli.main() == 1 and resets == []


def test_invalid_repeat_count_never_downloads(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run-benchmark', '--repeats', '0'])
    monkeypatch.setattr(
        cli,
        'ensure_sample_video',
        lambda *args: (_ for _ in ()).throw(AssertionError('must not download')),
    )
    assert cli.main() == 1


def test_videomme_credentials_are_checked_before_downloading(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run-videomme', '--paths', '1'])
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(
        vm_cli,
        'prepare_sample',
        lambda **kwargs: (_ for _ in ()).throw(AssertionError('must not download')),
    )
    assert vm_cli.main() == 1


@pytest.mark.parametrize(
    'entrypoint,argv,env',
    [
        (cli, ['run-benchmark', '--paths', '2', '--reset'], ('FRAME_SELECT_BUDGET', '0')),
        (cli, ['run-benchmark', '--paths', '3', '--reset'], ('OSS_ASR', 'invalid')),
        (vm_cli, ['run-videomme', '--paths', '3', '--reset'], ('GEMINI_MODEL', 'unpriced')),
        (vm_cli, ['run-videomme', '--paths', '2', '--reset'], ('VIDEOME_FRAME_SELECT_BUDGET', '0')),
    ],
)
def test_active_configuration_failure_has_no_side_effects(monkeypatch, entrypoint, argv, env):
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setenv(*env)
    side_effects = []
    for name in ('reset_catalog', 'ensure_sample_video', 'prepare_sample', 'apply_schema'):
        if hasattr(entrypoint, name):
            monkeypatch.setattr(entrypoint, name, lambda *args, **kwargs: side_effects.append(True))
    assert entrypoint.main() == 1 and side_effects == []


def test_skip_alias_removes_path_before_validation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        'argv',
        ['run-benchmark', '--paths', '1,3', '--skip-oss', '--video', str(tmp_path / 'missing.mp4')],
    )
    monkeypatch.setenv('OSS_ASR', 'invalid')
    seen = []
    monkeypatch.setattr(
        cli, 'ensure_sample_video', lambda *args: seen.append(True) or (tmp_path / 'missing.mp4')
    )
    monkeypatch.setattr(
        cli,
        'apply_schema',
        lambda *args: (_ for _ in ()).throw(
            cli.CatalogSchemaMismatch('fixture stop before insert')
        ),
    )
    assert cli.main() == 1 and seen == [True]


def test_guard_is_active_before_schema_mutations(monkeypatch, tmp_path, test_video):
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'run-benchmark',
            '--paths',
            '1',
            '--video',
            str(test_video),
            '--ledger',
            str(tmp_path / 'ledger.sqlite3'),
        ],
    )
    order = []

    @contextmanager
    def guard(*args, **kwargs):
        order.append('guard')
        yield
        order.append('guard_closed')

    def apply(*args):
        order.append('schema')
        raise cli.CatalogSchemaMismatch('stop before insertion')

    monkeypatch.setattr(cli.admission, 'provider_session', guard)
    monkeypatch.setattr(cli, 'apply_schema', apply)
    assert cli.main() == 1
    assert order[:2] == ['guard', 'schema']


def test_preflight_does_not_apply_or_reset(monkeypatch, tmp_path, test_video):
    monkeypatch.setattr(
        sys,
        'argv',
        ['run-benchmark', '--paths', '1', '--video', str(test_video), '--preflight', '--reset'],
    )
    for name in ('reset_catalog', 'apply_schema', 'run_benchmark'):
        monkeypatch.setattr(
            cli,
            name,
            lambda *args: (_ for _ in ()).throw(
                AssertionError('preflight must not mutate the catalog or call a model')
            ),
        )
    assert cli.main() == 0


def test_bad_budget_fails_before_download_or_reset(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run-benchmark', '--budget-usd', 'nan', '--reset'])
    monkeypatch.setattr(
        cli,
        'ensure_sample_video',
        lambda *args: (_ for _ in ()).throw(AssertionError('invalid admission must not download')),
    )
    assert cli.main() == 1
