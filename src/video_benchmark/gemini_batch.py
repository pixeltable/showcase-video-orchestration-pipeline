"""Optional batched multi-image Gemini vision for Path 2."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import pixeltable as pxt

from video_benchmark.udfs import (
    GEMINI_25_FLASH_INPUT_PER_M,
    _compute_cost_impl,
    _estimate_image_tokens_impl,
    _estimate_text_tokens_impl,
    _frame_prompt_impl,
    _gemini_text_impl,
)


def _frame_bytes(frame: Any) -> tuple[bytes, str]:
    import PIL.Image

    if isinstance(frame, PIL.Image.Image):
        buf = io.BytesIO()
        frame.save(buf, format='PNG')
        return buf.getvalue(), 'image/png'
    path = frame
    if not isinstance(path, str):
        path = getattr(frame, 'path', None) or getattr(frame, 'local_uri', None)
    if path:
        path = Path(str(path))
        if path.exists():
            suffix = path.suffix.lower()
            mime = 'image/png' if suffix == '.png' else 'image/jpeg'
            return path.read_bytes(), mime
    raise ValueError(f'Unsupported frame type for batch vision: {type(frame)}')


def _batch_prompt(query: str, positions: list[float]) -> str:
    lines = [
        f"For the analysis question '{query}', describe each keyframe below in 2-3 sentences.",
        'Return one paragraph per image, prefixed with its timestamp in brackets.',
        'Include who is visible, setting, and emotional tone. Do not invent names.',
        '',
        'Keyframes:',
    ]
    for pos in positions:
        lines.append(f'- [{pos:.1f}s]')
    return '\n'.join(lines)


def _parse_batch_response(text: str, positions: list[float]) -> list[str]:
    if len(positions) == 1:
        return [text.strip()]
    insights: list[str] = []
    for pos in positions:
        marker = f'[{pos:.1f}s]'
        start = text.find(marker)
        if start < 0:
            continue
        start += len(marker)
        next_start = len(text)
        for other in positions:
            if other == pos:
                continue
            other_marker = f'[{other:.1f}s]'
            idx = text.find(other_marker, start)
            if idx >= 0:
                next_start = min(next_start, idx)
        insights.append(text[start:next_start].strip())
    if len(insights) < len(positions):
        parts = [p.strip() for p in text.split('\n\n') if p.strip()]
        if len(parts) >= len(positions):
            return parts[: len(positions)]
        while len(insights) < len(positions):
            insights.append(text.strip() if len(insights) == 0 else '')
    return insights[: len(positions)]


def _batched_gemini_frame_context_impl(
    query: str,
    frame_rows: list | None,
    model: str,
    batch_size: int,
) -> list[dict]:
    if not frame_rows:
        return []
    rows = [r for r in frame_rows if isinstance(r, dict)]
    rows.sort(key=lambda r: float(r.get('pos_msec', 0.0)))

    results: list[dict] = []
    batch_size = max(1, int(batch_size))

    from google import genai

    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('GOOGLE_API_KEY or GEMINI_API_KEY required for batched vision')
    client = genai.Client(api_key=api_key)
    from google.genai import types

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        positions = [float(r.get('pos_msec', 0.0)) / 1000.0 for r in batch]
        parts: list[Any] = [types.Part.from_text(text=_batch_prompt(query, positions))]
        for row, pos in zip(batch, positions):
            data, mime = _frame_bytes(row.get('frame'))
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            parts.append(types.Part.from_text(text=_frame_prompt_impl(query, pos)))

        response = client.models.generate_content(model=model, contents=parts)
        response_dict = response.model_dump() if hasattr(response, 'model_dump') else {}
        text = _gemini_text_impl(response_dict) or str(getattr(response, 'text', '') or '')
        captions = _parse_batch_response(text, positions)

        usage = response_dict.get('usageMetadata') or response_dict.get('usage_metadata') or {}
        batch_in = int(usage.get('promptTokenCount', 0) or 0)
        batch_out = int(usage.get('candidatesTokenCount', 0) or 0)
        if batch_in == 0:
            batch_in = sum(_estimate_image_tokens_impl(query) for _ in batch)
        if batch_out == 0:
            batch_out = sum(_estimate_text_tokens_impl(c) for c in captions)
        per_in = batch_in // len(batch) if batch else 0
        per_out = batch_out // len(batch) if batch else 0

        for row, caption in zip(batch, captions):
            results.append(
                {
                    'pos_msec': float(row.get('pos_msec', 0.0)),
                    'segment_start': float(row.get('segment_start', 0.0)),
                    'frame_insight': caption,
                    'frame_cost': _compute_cost_impl(
                        per_in, per_out, GEMINI_25_FLASH_INPUT_PER_M
                    ),
                }
            )
    return results


@pxt.udf(is_deterministic=False)
def batched_gemini_frame_context(
    query: str,
    frame_rows: list | None,
    model: str,
    batch_size: int,
) -> list:
    """Run Gemini vision on keyframes in multi-image batches (Path 2 alternative)."""
    return _batched_gemini_frame_context_impl(query, frame_rows, model, batch_size)
