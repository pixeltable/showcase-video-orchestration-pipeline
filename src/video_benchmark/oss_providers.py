"""Local OSS vision + synthesis backends (llama.cpp default, Ollama optional)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import PIL.Image
import pixeltable as pxt
from pixeltable.functions.ollama import chat as ollama_chat
from pixeltable.utils.image import to_base64

from video_benchmark.udfs import (
    _frame_prompt_impl,
    _llama_response_text_impl,
    ollama_response_text,
)


def _ensure_ollama_host(ollama_host: str | None) -> None:
    """Pixeltable's ollama client reads host from env / registered client."""
    if ollama_host:
        os.environ['OLLAMA_HOST'] = ollama_host

_VISION_LLM_CACHE: dict[tuple[str, str, str, str, int], Any] = {}
_SYNTH_LLM_CACHE: dict[tuple[str, str, int], Any] = {}


def _frame_to_image_url_impl(frame: Any) -> str:
    if isinstance(frame, PIL.Image.Image):
        return f'data:image/png;base64,{to_base64(frame, format="png")}'
    if isinstance(frame, str):
        if frame.startswith(('http://', 'https://', 'data:', 'file://')):
            return frame
        return Path(frame).expanduser().resolve().as_uri()
    path = getattr(frame, 'path', None) or getattr(frame, 'local_uri', None)
    if path:
        return Path(str(path)).expanduser().resolve().as_uri()
    return str(frame)


def _vision_messages(frame: Any, query: Any, position_sec: float | None = None) -> list[dict]:
    image_url = _frame_to_image_url_impl(frame)
    return [
        {
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': _frame_prompt_impl(str(query), position_sec),
                },
                {'type': 'image_url', 'image_url': {'url': image_url}},
            ],
        }
    ]


def _gpu_layers() -> int:
    import llama_cpp

    llama_cpp_path = Path(llama_cpp.__file__).parent
    lib = llama_cpp.llama_cpp.load_shared_library('llama', llama_cpp_path / 'lib')
    return -1 if bool(lib.llama_supports_gpu_offload()) else 0


def _vision_chat_handler(
    chat_format: str | None,
    vision_repo_id: str,
    mmproj_repo_filename: str,
) -> Any:
    fmt = (chat_format or 'qwen2.5-vl').strip().lower().replace('_', '-')
    if fmt in {'qwen2.5-vl', 'qwen25-vl'}:
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler

        return Qwen25VLChatHandler.from_pretrained(
            repo_id=vision_repo_id,
            filename=mmproj_repo_filename,
        )
    if fmt in {'moondream', 'moondream2'}:
        from llama_cpp.llama_chat_format import MoondreamChatHandler

        return MoondreamChatHandler.from_pretrained(
            repo_id=vision_repo_id,
            filename=mmproj_repo_filename,
        )
    if fmt in {'llava-1-5', 'llava15', 'llava-1.5'}:
        from llama_cpp.llama_chat_format import Llava15ChatHandler

        return Llava15ChatHandler.from_pretrained(
            repo_id=vision_repo_id,
            filename=mmproj_repo_filename,
        )
    raise ValueError(
        f'Unsupported OSS_VISION_CHAT_FORMAT: {chat_format!r} '
        '(use qwen2.5-vl, moondream, or llava-1-5)'
    )


def _vision_n_ctx(chat_format: str | None) -> int:
    fmt = (chat_format or 'qwen2.5-vl').strip().lower().replace('_', '-')
    if fmt in {'qwen2.5-vl', 'qwen25-vl'}:
        return 4096
    return 2048


def _get_vision_llm(
    vision_repo_id: str,
    vision_repo_filename: str,
    mmproj_repo_filename: str,
    vision_chat_format: str | None,
) -> Any:
    import llama_cpp

    n_gpu_layers = _gpu_layers()
    fmt = (vision_chat_format or 'qwen2.5-vl').strip().lower()
    key = (fmt, vision_repo_id, vision_repo_filename, mmproj_repo_filename, n_gpu_layers)
    if key not in _VISION_LLM_CACHE:
        chat_handler = _vision_chat_handler(
            vision_chat_format, vision_repo_id, mmproj_repo_filename
        )
        _VISION_LLM_CACHE[key] = llama_cpp.Llama.from_pretrained(
            repo_id=vision_repo_id,
            filename=vision_repo_filename,
            chat_handler=chat_handler,
            n_ctx=_vision_n_ctx(vision_chat_format),
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
    return _VISION_LLM_CACHE[key]


def _get_synth_llm(synth_repo_id: str, synth_repo_filename: str) -> Any:
    import llama_cpp

    n_gpu_layers = _gpu_layers()
    key = (synth_repo_id, synth_repo_filename, n_gpu_layers)
    if key not in _SYNTH_LLM_CACHE:
        _SYNTH_LLM_CACHE[key] = llama_cpp.Llama.from_pretrained(
            repo_id=synth_repo_id,
            filename=synth_repo_filename,
            n_ctx=8192,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
    return _SYNTH_LLM_CACHE[key]


def _oss_insight_llama_impl(
    prompt_text: str,
    synth_repo_id: str,
    synth_repo_filename: str,
    synth_max_tokens: int = 2048,
) -> str:
    llm = _get_synth_llm(synth_repo_id, synth_repo_filename)
    response = llm.create_chat_completion(
        messages=[{'role': 'user', 'content': prompt_text}],
        max_tokens=int(synth_max_tokens or 2048),
        temperature=0.1,
        repeat_penalty=1.15,
    )
    return _llama_response_text_impl(response)


@pxt.udf(is_deterministic=False)
def oss_insight_llama(
    prompt_text: str,
    synth_repo_id: str,
    synth_repo_filename: str,
    synth_max_tokens: int = 2048,
) -> str:
    """Text-only synthesis via llama.cpp GGUF with a larger context window."""
    return _oss_insight_llama_impl(
        prompt_text, synth_repo_id, synth_repo_filename, synth_max_tokens
    )


def _oss_frame_insight_llama_impl(
    frame: Any,
    query: str,
    vision_repo_id: str,
    vision_repo_filename: str,
    mmproj_repo_filename: str,
    vision_chat_format: str | None,
    position_sec: float | None = None,
) -> str:
    llm = _get_vision_llm(
        vision_repo_id,
        vision_repo_filename,
        mmproj_repo_filename,
        vision_chat_format,
    )
    response = llm.create_chat_completion(
        messages=_vision_messages(frame, query, position_sec),
        max_tokens=256,
        temperature=0.2,
    )
    return _llama_response_text_impl(response)


@pxt.udf(is_deterministic=False)
def oss_frame_insight_llama(
    frame: pxt.Image,
    query: str,
    vision_repo_id: str,
    vision_repo_filename: str,
    mmproj_repo_filename: str,
    vision_chat_format: str | None,
    position_sec: float | None = None,
) -> str:
    """Query-aware per-keyframe insight via llama.cpp vision GGUF."""
    return _oss_frame_insight_llama_impl(
        frame,
        query,
        vision_repo_id,
        vision_repo_filename,
        mmproj_repo_filename,
        vision_chat_format,
        position_sec,
    )


def oss_frame_insight_expr(
    frame: Any,
    query: Any,
    position_sec: Any,
    *,
    backend: str,
    vision_model: str,
    vision_repo_id: str,
    vision_repo_filename: str,
    mmproj_repo_filename: str,
    vision_chat_format: str | None,
    ollama_host: str | None = None,
) -> Any:
    if backend == 'llama_cpp':
        return oss_frame_insight_llama(
            frame,
            query,
            vision_repo_id,
            vision_repo_filename,
            mmproj_repo_filename,
            vision_chat_format,
            position_sec,
        )
    _ensure_ollama_host(ollama_host)
    messages = _vision_messages(frame, query, position_sec)
    return ollama_response_text(
        ollama_chat(
            messages=messages,
            model=vision_model,
            options={'num_predict': 256, 'temperature': 0.2},
        )
    )


def oss_insight_expr(
    prompt_text: Any,
    *,
    backend: str,
    vision_model: str,
    synth_repo_id: str,
    synth_repo_filename: str,
    synth_max_tokens: int = 2048,
    ollama_host: str | None = None,
) -> Any:
    if backend == 'llama_cpp':
        return oss_insight_llama(
            prompt_text,
            synth_repo_id,
            synth_repo_filename,
            synth_max_tokens,
        )
    _ensure_ollama_host(ollama_host)
    messages = [{'role': 'user', 'content': prompt_text}]
    return ollama_response_text(
        ollama_chat(
            messages=messages,
            model=vision_model,
            options={'num_predict': int(synth_max_tokens or 2048), 'temperature': 0.2},
        )
    )
