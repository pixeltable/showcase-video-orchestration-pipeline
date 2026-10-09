"""A real local media graph: generate a clip, insert it, inspect its frames and audio.

No provider credentials, downloads, or model calls are used. The catalog is temporary.
"""

from __future__ import annotations

import fractions
import hashlib
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
    """Own preparation, reuse it for requests, and deliberately refresh a changed policy."""
    import pixeltable as pxt
    from pixeltable.functions.audio import audio_splitter
    from pixeltable.functions.image import resize
    from pixeltable.functions.video import extract_audio, frame_iterator, get_duration

    from video_benchmark import local_demo_rules as rules
    from video_benchmark.provenance import media_identity

    rules.preparations.clear()
    rules.reviews.clear()

    TableModel = pxt.model_base()

    class Clips(TableModel, name='clips'):
        clip_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        minimum_brightness: pxt.Float
        duration_sec = get_duration(video)  # noqa: F821
        audio = extract_audio(video, format='mp3')  # noqa: F821

    class Frames(
        TableModel, name='frames', base=Clips, iterator=frame_iterator(Clips.video, num_frames=4)
    ):
        position_sec = frame_attrs.time.astype(pxt.Float)  # noqa: F821
        thumbnail = resize(frame, (128, 96))  # noqa: F821
        brightness = rules.mean_brightness(frame)  # noqa: F821
        eligible = brightness >= minimum_brightness  # noqa: F821

    class AudioSegments(
        TableModel, name='audio_segments', base=Clips,
        iterator=audio_splitter(Clips.audio, duration=2.0),
    ):
        pass

    @pxt.query
    def candidate_frames(clip_id: str):
        return Frames.where((Frames.clip_id == clip_id) & Frames.eligible).order_by(
            Frames.position_sec
        ).select(Frames.position_sec, Frames.brightness)

    class Requests(TableModel, name='requests'):
        request_id = pxt.Column(type=pxt.String, primary_key=True)
        clip_id: pxt.String
        evidence = candidate_frames(clip_id)  # noqa: F821
        decision = rules.review_result(evidence, request_id)  # noqa: F821

    catalog = 'local_media_demo'
    pxt.create_dir(catalog)
    for _ in range(2):
        TableModel.update_all(catalog)
    clips = pxt.get_table(f'{catalog}.clips')
    source = make_demo_video(home / 'demo.mp4')
    source_identity = media_identity(source)
    status = clips.insert([
        {'clip_id': 'demo', 'video': str(source), 'minimum_brightness': 0.0}
    ])
    assert status.num_excs == 0, status
    frames = pxt.get_table(f'{catalog}.frames')
    segments = pxt.get_table(f'{catalog}.audio_segments')

    def preparation_snapshot() -> dict:
        thumbnails = list(frames.order_by(frames.position_sec).select(
            frames.position_sec, frames.thumbnail, frames.brightness
        ).collect())
        chunks = list(segments.order_by(segments.segment_start).select(
            segments.segment_start, segments.segment_end, path=segments.audio_segment.localpath
        ).collect())
        assert len(thumbnails) == 4
        assert all(row['thumbnail'].size == (128, 96) for row in thumbnails)
        assert len(chunks) >= 2
        return {
            'frames': [{
                'position_sec': row['position_sec'], 'thumbnail_size': [128, 96],
                'thumbnail_sha256': hashlib.sha256(row['thumbnail'].tobytes()).hexdigest(),
                'brightness': row['brightness'],
            } for row in thumbnails],
            'audio_segments': [{
                'segment_start': row['segment_start'], 'segment_end': row['segment_end'],
                'audio_sha256': media_identity(row['path'])['sha256'],
            } for row in chunks],
        }

    prepared = preparation_snapshot()
    requests = pxt.get_table(f'{catalog}.requests')
    status = requests.insert([
        {'request_id': request, 'clip_id': 'demo'} for request in ('first', 'second')
    ])
    assert status.num_excs == 0, status

    def decisions() -> dict[str, str]:
        return {row['request_id']: row['decision'] for row in requests.select(
            requests.request_id, requests.decision
        ).collect()}

    before = decisions()
    assert before == {request: '4 frames meet the review policy' for request in ('first', 'second')}
    assert len(rules.preparations) == 4 and len(rules.reviews) == 2
    # Editing a business rule updates eligible frames, but the cross-table query snapshot
    # remains unchanged until the application deliberately refreshes that request.
    clips.update({'minimum_brightness': 128.0}, where=clips.clip_id == 'demo')
    assert frames.where(frames.eligible).count() == 2
    assert decisions() == before
    status = requests.recompute_columns('evidence', where=requests.request_id == 'first')
    assert status.num_excs == 0, status
    after = decisions()
    assert after == {'first': '2 frames meet the review policy', 'second': before['second']}
    assert len(rules.preparations) == 4 and rules.reviews == ['first', 'second', 'first']
    assert preparation_snapshot() == prepared and media_identity(source) == source_identity
    result = {
        'pixeltable_version': pxt.__version__, 'provider_calls': 0,
        **prepared,
        'requests_before_policy_change': before, 'requests_after_explicit_refresh': after,
        'prepared_frames': len(rules.preparations), 'review_evaluations': list(rules.reviews),
        'source_and_preparation_unchanged': True,
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
