#!/usr/bin/env python3
"""Download the default Pursuit of Happyness sample video."""

from __future__ import annotations

from video_benchmark.runner import ensure_sample_video


def main() -> None:
    path = ensure_sample_video()
    print(f'Sample video: {path}')


if __name__ == '__main__':
    main()
