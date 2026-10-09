"""Path 3 local models via llama.cpp: a vision model captions keyframes, a text model answers.

`pixeltable.functions.llama_cpp.create_chat_completion` cannot set a chat handler (needed for
the vision projector) or the context size (the synthesis prompt needs 8K tokens), so these
two UDFs load the models themselves, once per process.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import PIL.Image
import pixeltable as pxt
from pixeltable.utils.image import to_base64

VISION_N_CTX = 4096
SYNTH_N_CTX = 8192

_models: dict[tuple, Any] = {}
_models_lock = threading.Lock()


def _gpu_layers() -> int:
    import llama_cpp

    lib = llama_cpp.llama_cpp.load_shared_library('llama', Path(llama_cpp.__file__).parent / 'lib')
    return -1 if bool(lib.llama_supports_gpu_offload()) else 0


def _chat_handler(chat_format: str, repo_id: str, mmproj_filename: str) -> Any:
    from llama_cpp import llama_chat_format

    handlers = {
        'qwen2.5-vl': llama_chat_format.Qwen25VLChatHandler,
        'moondream': llama_chat_format.MoondreamChatHandler,
        'llava-1-5': llama_chat_format.Llava15ChatHandler,
    }
    fmt = chat_format.strip().lower().replace('_', '-')
    if fmt not in handlers:
        raise ValueError(
            f'Unsupported OSS_VISION_CHAT_FORMAT {chat_format!r} (use {", ".join(handlers)})'
        )
    return handlers[fmt].from_pretrained(repo_id=repo_id, filename=mmproj_filename)


def _model(key: tuple, load: Any) -> Any:
    with _models_lock:
        if key not in _models:
            _models[key] = load()
        return _models[key]


def _vision_model(repo_id: str, filename: str, mmproj_filename: str, chat_format: str) -> Any:
    import llama_cpp

    return _model(
        ('vision', repo_id, filename, mmproj_filename, chat_format),
        lambda: llama_cpp.Llama.from_pretrained(
            repo_id=repo_id,
            filename=filename,
            chat_handler=_chat_handler(chat_format, repo_id, mmproj_filename),
            n_ctx=VISION_N_CTX,
            n_gpu_layers=_gpu_layers(),
            verbose=False,
        ),
    )


def _synth_model(repo_id: str, filename: str) -> Any:
    import llama_cpp

    return _model(
        ('synth', repo_id, filename),
        lambda: llama_cpp.Llama.from_pretrained(
            repo_id=repo_id,
            filename=filename,
            n_ctx=SYNTH_N_CTX,
            n_gpu_layers=_gpu_layers(),
            verbose=False,
        ),
    )


def completion_text_impl(response: dict) -> str:
    choices = response.get('choices') or [{}]
    message = choices[0].get('message') or {}
    return str(message.get('content') or '').strip()


def vision_messages_impl(frame: PIL.Image.Image, prompt: str) -> list[dict]:
    url = f'data:image/png;base64,{to_base64(frame, format="png")}'
    return [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': url}},
            ],
        }
    ]


@pxt.udf(is_deterministic=False)
def local_caption(
    frame: pxt.Image,
    prompt: str,
    *,
    repo_id: str,
    filename: str,
    mmproj_filename: str,
    chat_format: str,
) -> str:
    """Caption one keyframe with a local vision GGUF."""
    llm = _vision_model(repo_id, filename, mmproj_filename, chat_format)
    response = llm.create_chat_completion(
        messages=vision_messages_impl(frame, prompt), max_tokens=256, temperature=0.2
    )
    return completion_text_impl(response)


@pxt.udf(is_deterministic=False)
def local_synthesize(prompt: str, *, repo_id: str, filename: str, max_tokens: int) -> str:
    """Answer from text evidence with a local instruction-tuned GGUF."""
    llm = _synth_model(repo_id, filename)
    response = llm.create_chat_completion(
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=max_tokens,
        temperature=0.1,
        repeat_penalty=1.15,
    )
    return completion_text_impl(response)
