"""The Pixeltable pin is read from pyproject.toml."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pin_module():
    path = ROOT / 'scripts' / 'pixeltable_pin.py'
    spec = importlib.util.spec_from_file_location('pixeltable_pin', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_pin(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text())
    for dep in data['project']['dependencies']:
        if dep.startswith('pixeltable=='):
            return dep.split('==', 1)[1]
    raise AssertionError(f'{pyproject} has no pixeltable== dependency')


def test_pixeltable_pin_matches_pyproject_dependency():
    pyproject = ROOT / 'pyproject.toml'
    assert _pin_module().pixeltable_pin(pyproject) == _declared_pin(pyproject)


def test_pixeltable_pin_does_not_match_a_version_prefix(tmp_path: Path):
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text('[project]\nname = "example"\ndependencies = ["pixeltable==0.7.8"]\n')
    assert _pin_module().pixeltable_pin(pyproject) == '0.7.8'
    assert _pin_module().pixeltable_pin(pyproject) != '0.7'
