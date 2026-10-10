"""A real local media graph: generate a clip, insert it, inspect its frames and audio.

No provider credentials, downloads, or model calls are used. The catalog is temporary.
"""

from __future__ import annotations

import fractions
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def make_demo_video(
    path: Path,
    *,
    seconds: int = 4,
    fps: int = 8,
    sample_rate: int = 16000,
    codec: str | None = None,
) -> Path:
    """Small MP4 with a hard visual cut and a tone; no copyrighted sample required."""
    import av
    import numpy as np

    codec = codec or ('libx264' if 'libx264' in av.codecs_available else 'mpeg4')
    with av.open(str(path), 'w') as out:
        video = out.add_stream(codec, rate=fps)
        video.width, video.height, video.pix_fmt = 64, 48, 'yuv420p'
        audio = out.add_stream('aac', rate=sample_rate)
        audio.layout = 'mono'
        for index in range(seconds * fps):
            shade = 30 if index < seconds * fps // 2 else 220
            frame = av.VideoFrame.from_ndarray(
                np.full((48, 64, 3), shade, np.uint8), format='rgb24'
            )
            for packet in video.encode(frame):
                out.mux(packet)
        for packet in video.encode():
            out.mux(packet)
        timeline = np.arange(seconds * sample_rate) / sample_rate
        wave = (0.2 * np.sin(2 * np.pi * 440 * timeline)).astype(np.float32)
        for start in range(0, len(wave), 1024):
            frame = av.AudioFrame.from_ndarray(
                wave[start : start + 1024].reshape(1, -1), format='fltp', layout='mono'
            )
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = fractions.Fraction(1, sample_rate)
            for packet in audio.encode(frame):
                out.mux(packet)
        for packet in audio.encode():
            out.mux(packet)
    return path


def run_local_demo(home: Path) -> dict:
    """Own preparation, reuse it for requests, and deliberately refresh a changed policy."""
    from video_benchmark.local_graph import LocalMediaGraph

    graph = LocalMediaGraph(make_demo_video(home / 'demo.mp4'))
    before = {row['request_id']: row['decision'] for row in graph.state()['requests']}
    graph.change_policy(128.0)
    stale = graph.state()
    assert all(row['stale'] for row in stale['requests'])
    assert {row['request_id']: row['decision'] for row in stale['requests']} == before
    graph.refresh('first')
    after = graph.state()
    result = {
        **graph.initial_preparation,
        **{
            key: after[key]
            for key in (
                'pixeltable_version',
                'provider_calls',
                'prepared_frames',
                'review_evaluations',
                'source_and_preparation_unchanged',
            )
        },
        'requests_before_policy_change': before,
        'requests_after_explicit_refresh': {
            row['request_id']: row['decision'] for row in after['requests']
        },
    }
    assert result['source_and_preparation_unchanged']
    assert result['prepared_frames'] == 4
    assert result['review_evaluations'] == ['first', 'second', 'first']
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix='pxt-local-media-'))
    os.environ['PIXELTABLE_HOME'] = str(home)
    os.environ['PIXELTABLE_PGDATA'] = str(home / 'pgdata')
    os.environ.pop('PIXELTABLE_DB_CONNECT_STR', None)
    try:
        run_local_demo(home)
    finally:
        if (home / 'pgdata').exists():
            from pixeltable_pgserver import pg_ctl

            try:
                pg_ctl(['-m', 'fast', '-w', 'stop'], pgdata=home / 'pgdata')
            except subprocess.CalledProcessError:
                pass
        if (home / 'pgdata' / 'postmaster.pid').exists():
            print(f'Catalog preserved at {home}: database shutdown did not complete.', flush=True)
        else:
            shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
