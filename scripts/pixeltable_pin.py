#!/usr/bin/env python3
"""Read the Pixeltable pin from pyproject.toml. That file is the only pin humans edit."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pixeltable_pin(pyproject: Path | None = None) -> str:
    path = pyproject or ROOT / 'pyproject.toml'
    data = tomllib.loads(path.read_text())
    for dep in data['project']['dependencies']:
        if dep.startswith('pixeltable=='):
            return dep.split('==', 1)[1].strip()
    raise SystemExit(f'{path} has no pixeltable== pin')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='Exit 1 unless the installed pixeltable version matches the pin',
    )
    args = parser.parse_args()
    pin = pixeltable_pin()
    if not args.check:
        print(pin)
        return 0
    import pixeltable as pxt

    installed = pxt.__version__
    if installed != pin:
        print(f'Installed pixeltable {installed} does not match pyproject.toml pin {pin}')
        return 1
    print(f'pixeltable {installed} matches pyproject.toml')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
