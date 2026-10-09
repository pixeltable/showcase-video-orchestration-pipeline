"""Preparing video for Nova: pass H.264 through, re-encode anything else at Nova's sampling."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from conftest import make_test_video

from video_benchmark import providers
from video_benchmark.providers import (
    NOVA_INLINE_VIDEO_BYTES,
    NOVA_MAX_FRAMES,
    nova_encode_args,
    nova_input_impl,
)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None,
    reason='ffmpeg and ffprobe are not on PATH',
)


def _option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def test_encode_samples_one_frame_per_second_up_to_sixteen_minutes():
    assert _option(nova_encode_args(255.0), '-vf').startswith('fps=1.000000,')


def test_encode_spreads_960_frames_over_longer_videos_within_the_limit():
    duration = 3268.5  # the longest Video-MME video in the sample, 54.5 minutes
    args = nova_encode_args(duration)
    fps = float(_option(args, '-vf').split(',', 1)[0].removeprefix('fps='))
    assert fps * duration == pytest.approx(NOVA_MAX_FRAMES, abs=0.01)
    assert int(_option(args, '-maxrate')) * duration / 8 < NOVA_INLINE_VIDEO_BYTES
    assert '-an' in args


def _streams(path) -> list[dict]:
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,nb_frames']
        + ['-of', 'json', str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)['streams']


@needs_ffmpeg
def test_h264_within_the_limit_is_sent_as_is(tmp_path, monkeypatch):
    import av

    if 'libx264' not in av.codecs_available:
        pytest.skip('PyAV build has no libx264 encoder')
    monkeypatch.setattr(providers, 'NOVA_CACHE', tmp_path / 'nova')
    video = make_test_video(tmp_path / 'h264.mp4', codec='libx264')
    assert nova_input_impl(video) == video
    assert not (tmp_path / 'nova').exists()


@needs_ffmpeg
def test_other_codecs_are_reencoded_once_to_h264_without_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'NOVA_CACHE', tmp_path / 'nova')
    video = make_test_video(tmp_path / 'mpeg4.mp4', codec='mpeg4')
    out = nova_input_impl(video)
    assert out is not None and out.parent == tmp_path / 'nova'
    streams = _streams(out)
    assert [(s['codec_type'], s['codec_name']) for s in streams] == [('video', 'h264')]
    assert int(streams[0]['nb_frames']) == 4  # 4 seconds at 1 fps
    # A second question about the same video reuses the cached file.
    mtime = out.stat().st_mtime_ns
    assert nova_input_impl(video) == out and out.stat().st_mtime_ns == mtime


@pytest.mark.parametrize('model_error', [False, True])
def test_transcript_cleanup_does_not_replace_a_paid_response_or_primary_error(
    tmp_path, monkeypatch, model_error
):
    audio = tmp_path / 'tiny.mp3'
    audio.write_bytes(b'audio')
    uploaded = SimpleNamespace(state=SimpleNamespace(name='ACTIVE'), name='file-1', uri='gs://audio')

    class Client:
        @property
        def aio(self):
            return self

        @property
        def files(self):
            return self

        @property
        def models(self):
            return self

        async def upload(self, **kwargs):
            return uploaded

        async def generate_content(self, **kwargs):
            if model_error:
                raise ValueError('model failure')
            return SimpleNamespace(
                model_dump=lambda: {'usage_metadata': {'prompt_token_count': 10}}
            )

        async def delete(self, **kwargs):
            raise RuntimeError('cleanup failure')

    monkeypatch.setattr(providers, '_gemini_client', Client)
    monkeypatch.setattr(providers, 'GEMINI_INLINE_AUDIO_BYTES', 0)
    call = providers.transcribe_response.py_fn(str(audio), model='test', prompt='test')
    if model_error:
        with pytest.raises(ValueError, match='model failure'):
            asyncio.run(call)
    else:
        assert asyncio.run(call)['usage_metadata']['prompt_token_count'] == 10


def test_uploaded_audio_processing_has_a_deadline(tmp_path, monkeypatch):
    audio = tmp_path / 'tiny.mp3'
    audio.write_bytes(b'audio')
    uploaded = SimpleNamespace(state=SimpleNamespace(name='PROCESSING'), name='file-1')
    deleted = []

    class Client:
        @property
        def aio(self):
            return self

        @property
        def files(self):
            return self

        async def upload(self, **kwargs):
            return uploaded

        async def get(self, **kwargs):
            return uploaded

        async def delete(self, **kwargs):
            deleted.append(kwargs['name'])

    monkeypatch.setattr(providers, '_gemini_client', Client)
    monkeypatch.setattr(providers, 'GEMINI_INLINE_AUDIO_BYTES', 0)
    monkeypatch.setattr(providers, 'GEMINI_FILE_TIMEOUT_SEC', 0.01)
    monkeypatch.setattr(providers, 'GEMINI_FILE_POLL_SEC', 0.001)
    with pytest.raises(TimeoutError):
        asyncio.run(providers.transcribe_response.py_fn(str(audio), model='test', prompt='test'))
    assert deleted == ['file-1']
