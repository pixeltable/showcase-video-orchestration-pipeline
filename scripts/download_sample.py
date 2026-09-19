#!/usr/bin/env python3
"""Download the default Pursuit of Happyness sample video."""

from __future__ import annotations

import urllib.request

from video_benchmark.config import ASSETS_DIR, DEFAULT_SAMPLE, PURSUIT_VIDEO_URL


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if DEFAULT_SAMPLE.exists():
        print(f'Sample already exists: {DEFAULT_SAMPLE}')
        return
    print(f'Downloading {PURSUIT_VIDEO_URL} ...')
    urllib.request.urlretrieve(PURSUIT_VIDEO_URL, DEFAULT_SAMPLE)
    print(f'Saved to {DEFAULT_SAMPLE}')


if __name__ == '__main__':
    main()
