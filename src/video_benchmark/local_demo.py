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
    path: Path, *, seconds: int = 4, fps: int = 8, sample_rate: int = 16000,
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
                wave[start:start + 1024].reshape(1, -1), format='fltp', layout='mono'
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
    """Apply an actual TableModel graph twice, insert one real media row, verify outputs."""
    import pixeltable as pxt
    from pixeltable.functions.audio import audio_splitter
    from pixeltable.functions.image import resize
    from pixeltable.functions.video import extract_audio, frame_iterator, get_duration

    TableModel = pxt.model_base()

    class Clips(TableModel, name='clips'):
        clip_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration_sec = get_duration(video)  # noqa: F821
        audio = extract_audio(video, format='mp3')  # noqa: F821

    class Frames(
        TableModel, name='frames', base=Clips, iterator=frame_iterator(Clips.video, num_frames=4)
    ):
        position_sec = frame_attrs.time.astype(pxt.Float)  # noqa: F821
        thumbnail = resize(frame, (128, 96))  # noqa: F821

    class AudioSegments(
        TableModel, name='audio_segments', base=Clips,
        iterator=audio_splitter(Clips.audio, duration=2.0),
    ):
        pass

    catalog = 'local_media_demo'
    pxt.create_dir(catalog)
    for _ in range(2):
        TableModel.update_all(catalog)
    status = pxt.get_table(f'{catalog}.clips').insert([
        {'clip_id': 'demo', 'video': str(make_demo_video(home / 'demo.mp4'))}
    ])
    assert status.num_excs == 0, status
    frames = pxt.get_table(f'{catalog}.frames')
    thumbnails = list(frames.order_by(frames.position_sec).select(
        frames.position_sec, frames.thumbnail
    ).collect())
    segments = pxt.get_table(f'{catalog}.audio_segments')
    chunks = list(segments.select(segments.segment_start, segments.segment_end).collect())
    assert len(thumbnails) == 4
    assert all(row['thumbnail'].size == (128, 96) for row in thumbnails)
    assert len(chunks) >= 2
    result = {
        'pixeltable_version': pxt.__version__, 'provider_calls': 0,
        'frames': [{'position_sec': row['position_sec'], 'thumbnail_size': [128, 96]}
                   for row in thumbnails],
        'audio_segments': chunks,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix='pxt-local-media-'))
    os.environ['PIXELTABLE_HOME'] = str(home)
    try:
        run_local_demo(home)
    finally:
        if (home / 'pgdata').exists():
            from pixeltable_pgserver import pg_ctl

            try:
                pg_ctl(['-m', 'fast', '-w', 'stop'], pgdata=home / 'pgdata')
            except subprocess.CalledProcessError:
                pass
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
