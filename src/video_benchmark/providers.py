"""Provider calls that `pixeltable.functions` does not cover in the form this benchmark needs.

Everything else goes through Pixeltable's own UDFs: `gemini.generate_content`,
`bedrock.converse`, and `fal.run`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import subprocess
from pathlib import Path

import pixeltable as pxt

from video_benchmark.config import ASSETS_DIR

# Gemini accepts inline media up to 20 MB per request; larger audio goes through the Files API.
GEMINI_INLINE_AUDIO_BYTES = 15 * 2**20
GEMINI_FILE_TIMEOUT_SEC = 300.0
GEMINI_FILE_POLL_SEC = 2.0
_logger = logging.getLogger(__name__)
# Perception calls (keyframe captions, transcription) need no reasoning; thinking tokens bill as
# output. Answer-writing calls keep the model's default thinking.
ANSWER_CONFIG = {'max_output_tokens': 4096}
NO_THINKING = {**ANSWER_CONFIG, 'thinking_config': {'thinking_budget': 0}}
LOW_MEDIA_RESOLUTION = {**ANSWER_CONFIG, 'media_resolution': 'MEDIA_RESOLUTION_LOW'}


def _gemini_client():
    from google import genai

    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    return genai.Client(api_key=api_key)


@pxt.udf(is_deterministic=False)
async def transcribe_response(
    audio: pxt.Audio, *, model: str, prompt: str, config: dict | None = None
) -> dict:
    """Gemini transcription that keeps the whole response.

    `pixeltable.functions.gemini.transcribe` returns only the text; cost accounting needs the
    response's `usage_metadata`.
    """
    from google.genai import types

    client = _gemini_client()
    path = Path(audio)
    mime_type = mimetypes.guess_type(path.name)[0] or 'audio/mpeg'
    config_ = types.GenerateContentConfig(**config) if config else None
    if path.stat().st_size <= GEMINI_INLINE_AUDIO_BYTES:
        part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)
        response = await client.aio.models.generate_content(
            model=model, contents=[part, prompt], config=config_
        )
        return response.model_dump()
    uploaded = await asyncio.wait_for(
        client.aio.files.upload(file=str(path), config={'mime_type': mime_type}),
        timeout=GEMINI_FILE_TIMEOUT_SEC,
    )
    try:
        async with asyncio.timeout(GEMINI_FILE_TIMEOUT_SEC):
            while uploaded.state is not None and uploaded.state.name == 'PROCESSING':
                await asyncio.sleep(GEMINI_FILE_POLL_SEC)
                uploaded = await client.aio.files.get(name=uploaded.name)
            if uploaded.state is not None and uploaded.state.name == 'FAILED':
                raise RuntimeError(f'Gemini could not process uploaded audio {path.name}')
        part = types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime_type)
        response = await client.aio.models.generate_content(
            model=model, contents=[part, prompt], config=config_
        )
        return response.model_dump()
    finally:
        # A cleanup failure must never erase a paid response and trigger another model call.
        try:
            await asyncio.wait_for(client.aio.files.delete(name=uploaded.name), timeout=30.0)
        except Exception as exc:
            _logger.warning('Could not delete temporary Gemini file %s: %s', uploaded.name, exc)


def gemini_text_impl(response: dict) -> str:
    """Answer text of a generate_content response (thought parts are not returned by default)."""
    for candidate in response.get('candidates') or []:
        parts = (candidate.get('content') or {}).get('parts') or []
        texts = [str(p['text']) for p in parts if p.get('text') and not p.get('thought')]
        if texts:
            return '\n'.join(texts).strip()
    return ''


@pxt.udf
def gemini_text(response: dict) -> str:
    return gemini_text_impl(response)


@pxt.udf(is_deterministic=False)
def fal_upload(video: pxt.Video) -> str:
    """Upload a local clip to fal storage; `fal-ai/video-understanding` takes a URL."""
    import fal_client

    return fal_client.upload_file(video)


# Bedrock caps an inline request at 25 MB, and the video travels base64-encoded (4/3 larger).
NOVA_INLINE_VIDEO_BYTES = 18 * 10**6
# What Nova Lite and Pro read from a video: frames resized to 672x672, sampled at 1 fps up to
# 16 minutes and as 960 frames spread over longer videos. The audio track is not used.
NOVA_FRAME_SIDE = 672
NOVA_MAX_FRAMES = 960
NOVA_CACHE = ASSETS_DIR / 'nova'


def nova_encode_args(duration_sec: float) -> list[str]:
    """ffmpeg output options for the frames Nova samples: H.264 at Nova's frame rate, sides of at
    most 672 px, no audio, and a bitrate cap that keeps the file under the inline limit."""
    fps = min(1.0, NOVA_MAX_FRAMES / duration_sec)
    maxrate = int(0.85 * 8 * NOVA_INLINE_VIDEO_BYTES / duration_sec)
    side = NOVA_FRAME_SIDE
    return [
        '-an',
        '-vf',
        f"fps={fps:.6f},scale=w='trunc(min(iw,{side})/2)*2':h='trunc(min(ih,{side})/2)*2'",
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '23',
        '-maxrate',
        str(maxrate),
        '-bufsize',
        str(int(2 * maxrate / fps)),
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
    ]


def _probe(path: Path) -> tuple[str, float]:
    """The first video stream's codec and the container's duration in seconds."""
    out = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=codec_name:format=duration',
            '-of',
            'json',
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    info = json.loads(out)
    return info['streams'][0]['codec_name'], float(info['format']['duration'])


def nova_input_impl(path: Path) -> Path | None:
    """The file to send Nova: the video itself when it is H.264 within the inline limit, else an
    H.264 re-encode of the frames Nova samples, cached under assets/nova/ so the questions about
    one video share it. None when even the re-encode exceeds the limit.

    Nova rejects AV1, the codec of most Video-MME downloads, as invalid input.
    """
    for binary in ('ffmpeg', 'ffprobe'):
        if shutil.which(binary) is None:
            raise RuntimeError(f'Path 5 needs {binary} on PATH to prepare video for Nova')
    codec, duration = _probe(path)
    if codec == 'h264' and path.stat().st_size <= NOVA_INLINE_VIDEO_BYTES:
        return path
    args = nova_encode_args(duration)
    stat = path.stat()
    source = f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{args}'
    out = NOVA_CACHE / f'{path.stem}-{hashlib.sha256(source.encode()).hexdigest()[:12]}.mp4'
    if not out.exists():
        NOVA_CACHE.mkdir(parents=True, exist_ok=True)
        partial = out.with_suffix(f'.{os.getpid()}.partial.mp4')
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-y', '-i', str(path), *args, str(partial)], check=True
        )
        partial.replace(out)
    return out if out.stat().st_size <= NOVA_INLINE_VIDEO_BYTES else None


@pxt.udf
def nova_inline_video(video: pxt.Video) -> pxt.Video | None:
    """The video as Nova reads it inline, or None (Pixeltable then skips the Nova call)."""
    out = nova_input_impl(Path(video))
    return None if out is None else str(out)


@pxt.udf
def nova_video_messages(video: pxt.Video, prompt: str) -> list:
    """Bedrock Converse input; `bedrock.converse` reads the video file into `source.bytes`."""
    return [
        {
            'role': 'user',
            'content': [
                {'video': {'format': 'mp4', 'source': {'bytes': video}}},
                {'text': prompt},
            ],
        }
    ]


def nova_text_impl(response: dict) -> str:
    parts = ((response.get('output') or {}).get('message') or {}).get('content') or []
    return '\n'.join(str(p['text']) for p in parts if p.get('text')).strip()


@pxt.udf
def nova_text(response: dict) -> str:
    return nova_text_impl(response)
