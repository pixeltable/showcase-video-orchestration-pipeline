"""Thin Pixeltable UDFs for costing, prompts, and aggregation."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path

import pixeltable as pxt

GEMINI_25_FLASH_INPUT_PER_M = 1.50
GEMINI_25_FLASH_OUTPUT_PER_M = 1.50
GEMINI_IMAGE_TOKENS = 258
GEMINI_VIDEO_TOKENS_PER_SEC = 263
GEMINI_VIDEO_MIN_TOKENS = 1024
GEMINI_AUDIO_TOKENS_PER_SEC = 32
# Approximate wrapper overhead for frame_prompt / native_prompt (heuristics undercount otherwise).
_FRAME_PROMPT_OVERHEAD_TOKENS = 80
_NATIVE_PROMPT_OVERHEAD_TOKENS = 20


def _gemini_text_impl(response: pxt.Json) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return str(response or '')
    for candidate in response.get('candidates') or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get('content') or {}
        parts = content.get('parts') or []
        texts = [str(part['text']) for part in parts if isinstance(part, dict) and part.get('text')]
        if texts:
            return '\n'.join(texts).strip()
    return ''


@pxt.udf
def gemini_text(response: pxt.Json) -> str:
    return _gemini_text_impl(response)


def _llama_response_text_impl(response: pxt.Json) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response or '').strip()
    choices = response.get('choices') or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get('message') or {}
        if isinstance(message, dict) and message.get('content'):
            return str(message['content']).strip()
    return ''


@pxt.udf
def ollama_response_text(response: pxt.Json) -> str:
    """Extract assistant text from Ollama chat/generate JSON."""
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response or '').strip()
    message = response.get('message') or {}
    if isinstance(message, dict) and message.get('content'):
        return str(message['content']).strip()
    return _llama_response_text_impl(response)


@pxt.udf
def zero_cost() -> float:
    return 0.0


def _estimate_text_tokens_impl(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


@pxt.udf
def estimate_text_tokens(text: str | None) -> int:
    return _estimate_text_tokens_impl(text)


@pxt.udf
def estimate_video_tokens(duration_sec: float | None, query: str) -> int:
    duration = float(duration_sec or 0.0)
    query_tokens = max(1, len(query or '') // 4)
    video_tokens = max(GEMINI_VIDEO_MIN_TOKENS, int(duration * GEMINI_VIDEO_TOKENS_PER_SEC))
    return video_tokens + query_tokens + _NATIVE_PROMPT_OVERHEAD_TOKENS


def _estimate_image_tokens_impl(query: str) -> int:
    return (
        GEMINI_IMAGE_TOKENS
        + max(1, len(query or '') // 4)
        + _FRAME_PROMPT_OVERHEAD_TOKENS
    )


@pxt.udf
def estimate_image_tokens(query: str) -> int:
    return _estimate_image_tokens_impl(query)


def _gemini_usage_tokens_impl(response: pxt.Json) -> tuple[int, int]:
    if not isinstance(response, dict):
        return 0, 0
    usage = response.get('usageMetadata') or response.get('usage_metadata') or {}
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(usage.get('promptTokenCount', 0) or usage.get('prompt_token_count', 0) or 0)
    # Do not fall back to totalTokenCount — that is prompt + candidates combined.
    output = int(
        usage.get('candidatesTokenCount', 0) or usage.get('candidates_token_count', 0) or 0
    )
    return prompt, output


@pxt.udf
def gemini_prompt_tokens(response: pxt.Json) -> int:
    return _gemini_usage_tokens_impl(response)[0]


@pxt.udf
def gemini_output_tokens(response: pxt.Json) -> int:
    return _gemini_usage_tokens_impl(response)[1]


def _resolved_gemini_cost_impl(
    actual_input_tokens: int,
    actual_output_tokens: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    rate_per_m: float,
) -> float:
    """Prefer API usage_metadata token counts when present, else heuristic estimates."""
    if int(actual_input_tokens or 0) + int(actual_output_tokens or 0) > 0:
        return _compute_cost_impl(
            int(actual_input_tokens or 0),
            int(actual_output_tokens or 0),
            rate_per_m,
        )
    return _compute_cost_impl(
        int(estimated_input_tokens or 0),
        int(estimated_output_tokens or 0),
        rate_per_m,
    )


@pxt.udf
def resolved_gemini_cost(
    actual_input_tokens: int,
    actual_output_tokens: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    rate_per_m: float,
) -> float:
    return _resolved_gemini_cost_impl(
        actual_input_tokens,
        actual_output_tokens,
        estimated_input_tokens,
        estimated_output_tokens,
        rate_per_m,
    )


def _compute_cost_impl(input_tokens: int, output_tokens: int, rate_per_m: float) -> float:
    in_cost = int(input_tokens) * float(rate_per_m) / 1_000_000
    out_cost = int(output_tokens) * GEMINI_25_FLASH_OUTPUT_PER_M / 1_000_000
    return float(in_cost + out_cost)


def _native_prompt_impl(query: str) -> str:
    return (
        f'Analyze this video and answer the following question thoroughly.\n\n'
        f'Question: {query}'
    )


@pxt.udf
def native_prompt(query: str) -> str:
    return _native_prompt_impl(query)


def _frame_prompt_impl(query: str, position_sec: float | None = None) -> str:
    time_anchor = ''
    if position_sec is not None:
        time_anchor = f'This keyframe is at {float(position_sec):.1f}s in the video. '
    return (
        f"For the analysis question '{query}', {time_anchor}"
        f'describe this keyframe in 2-3 sentences. '
        f'Include: who is visible and what they are doing, the setting, any visible text '
        f'or signage, facial expressions, laughter or gestures, who appears to be speaking, '
        f'emotional tone, and whether this looks like an interview, meeting, '
        f'or conversation. Describe only what is visible; do not invent names or plot details.'
    )


@pxt.udf
def frame_prompt(query: str, position_sec: float | None = None) -> str:
    return _frame_prompt_impl(query, position_sec)


@pxt.udf
def gemini_transcribe_prompt() -> str:
    return (
        'Transcribe this audio with timestamps and speaker labels. '
        'Return one line per utterance in this format:\n'
        '[mm:ss] Speaker N: spoken text\n'
        'Use Speaker 1, Speaker 2, etc. Do not include any other commentary.'
    )


def _parse_timestamp_sec(token: str) -> float | None:
    cleaned = token.strip().strip('[]')
    if cleaned.endswith('s'):
        cleaned = cleaned[:-1]
    if ':' in cleaned:
        parts = cleaned.split(':')
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60.0 + float(parts[1])
            if len(parts) == 3:
                return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        except ValueError:
            return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_diarized_transcript_impl(text: str, chunk_offset_sec: float = 0.0) -> list[dict]:
    lines: list[dict] = []
    if not text or not str(text).strip():
        return lines
    pattern = re.compile(
        r'^\s*\[(?P<ts>[^\]]+)\]\s*(?:(?P<speaker>Speaker\s*\d+|SPEAKER_\d+):\s*)?(?P<body>.+)\s*$',
        re.IGNORECASE,
    )
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            ts = _parse_timestamp_sec(match.group('ts') or '')
            start = chunk_offset_sec + (ts if ts is not None else 0.0)
            speaker = (match.group('speaker') or '').strip()
            body = (match.group('body') or '').strip()
            entry: dict = {
                'segment_start': start,
                'segment_end': start,
                'text': body,
            }
            if speaker:
                entry['speaker'] = speaker
            lines.append(entry)
            continue
        if lines:
            lines[-1]['text'] = f"{lines[-1]['text']} {line}".strip()
        else:
            lines.append(
                {
                    'segment_start': chunk_offset_sec,
                    'segment_end': chunk_offset_sec,
                    'text': line,
                }
            )
    return lines


@pxt.udf
def parse_diarized_transcript(text: str, chunk_offset_sec: float) -> list:
    return _parse_diarized_transcript_impl(text, float(chunk_offset_sec or 0.0))


def _extract_whisper_segments_impl(asr_raw: pxt.Json, chunk_offset_sec: float = 0.0) -> list[dict]:
    if not isinstance(asr_raw, dict):
        return []
    offset = float(chunk_offset_sec or 0.0)
    segments: list[dict] = []
    for seg in asr_raw.get('segments') or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get('text', '')).strip()
        if not text:
            continue
        start = offset + float(seg.get('start', 0.0) or 0.0)
        end = offset + float(seg.get('end', start) or start)
        segments.append({'segment_start': start, 'segment_end': end, 'text': text})
    if not segments:
        full_text = str(asr_raw.get('text', '')).strip()
        if full_text:
            segments.append(
                {
                    'segment_start': offset,
                    'segment_end': offset,
                    'text': full_text,
                }
            )
    return segments


@pxt.udf
def extract_whisper_segments(asr_raw: pxt.Json, chunk_offset_sec: float) -> list:
    return _extract_whisper_segments_impl(asr_raw, float(chunk_offset_sec or 0.0))


def _extract_whisperx_segments_impl(
    diarized: pxt.Json, chunk_offset_sec: float = 0.0
) -> list[dict]:
    if not isinstance(diarized, dict):
        return []
    offset = float(chunk_offset_sec or 0.0)
    segments: list[dict] = []
    for seg in diarized.get('segments') or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get('text', '')).strip()
        if not text:
            continue
        start = offset + float(seg.get('start', 0.0) or 0.0)
        end = offset + float(seg.get('end', start) or start)
        speaker = str(seg.get('speaker', '') or '').strip()
        entry: dict = {
            'segment_start': start,
            'segment_end': end,
            'text': text,
        }
        if speaker:
            entry['speaker'] = speaker
        segments.append(entry)
    return segments


@pxt.udf
def extract_whisperx_segments(diarized: pxt.Json, chunk_offset_sec: float) -> list:
    return _extract_whisperx_segments_impl(diarized, float(chunk_offset_sec or 0.0))


def _merge_transcript_segment_lists_impl(rows: list | None) -> list:
    merged: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        segment_lines = row.get('segment_lines')
        if isinstance(segment_lines, list):
            for seg in segment_lines:
                if isinstance(seg, dict):
                    merged.append(seg)
            continue
        text = str(row.get('text', '')).strip()
        if text:
            merged.append(
                {
                    'segment_start': float(row.get('segment_start', 0.0)),
                    'segment_end': row.get('segment_end'),
                    'text': text,
                    **({'speaker': row['speaker']} if row.get('speaker') else {}),
                }
            )
    merged.sort(key=lambda item: float(item.get('segment_start', 0.0)))
    return merged


@pxt.udf
def merge_transcript_segment_lists(rows: list | None) -> list:
    return _merge_transcript_segment_lists_impl(rows)


def _format_transcript_line(item: dict) -> str:
    start = float(item.get('segment_start', 0.0))
    text = str(item.get('text', '')).strip()
    speaker = str(item.get('speaker', '') or '').strip()
    if speaker:
        return f'[{start:.1f}s] {speaker}: {text}'
    return f'[{start:.1f}s] {text}'


def _is_usable_transcript_chunk(text: str, segment_start: float) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower.startswith('transcribe this audio'):
        return False
    if segment_start < 15.0 and len(cleaned) < 15:
        return False
    return True


def _assemble_benchmark_context_impl(
    question: str,
    transcript_context: list | None,
    frame_context: list | None,
    vision_label: str = 'Vision',
) -> str:
    parts = [
        'You are a multimodal video analyst. Using only the evidence below, answer the question.',
        f'\nANALYSIS QUESTION: {question}',
        '\nA full audio transcript is provided below; use it for speakers and dialogue.',
    ]

    transcript_lines: list[str] = []
    for item in transcript_context or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        start = float(item.get('segment_start', 0.0))
        if not _is_usable_transcript_chunk(text, start):
            continue
        transcript_lines.append(_format_transcript_line(item))
    if transcript_lines:
        transcript_str = '\n'.join(transcript_lines)
    else:
        transcript_str = '[no speech detected in audio chunks]'
    parts.append(f'\n<audio_transcript>\n{transcript_str}\n</audio_transcript>')

    frame_lines: list[str] = []
    for item in frame_context or []:
        if not isinstance(item, dict):
            continue
        pos_msec = float(item.get('pos_msec', 0.0))
        segment_start = float(item.get('segment_start', 0.0))
        insight = str(item.get('frame_insight', '')).strip() or '(none)'
        frame_lines.append(
            f'[{pos_msec / 1000.0:.2f}s | segment {segment_start:.1f}s] '
            f'{vision_label}: {insight}'
        )
    frame_str = '\n'.join(frame_lines) if frame_lines else 'N/A'
    parts.append(f'\n<visual_keyframe_timeline>\n{frame_str}\n</visual_keyframe_timeline>')

    parts.append(
        '\nWrite a cohesive chronological summary. Prefer this structure (match native '
        'video-analyst quality):\n'
        '**Main Activities:** — numbered list (max 6) of what happens, in order\n'
        '**Speakers:** — map speaker labels (Speaker N / SPEAKER_XX) to roles/names when known\n'
        '**Visual Events:** — bullet list with timestamp ranges '
        '(e.g. 0:00-0:30), not per-frame spam\n\n'
        'Use the audio transcript for speakers and quoted dialogue; weave keyframe observations '
        'into the narrative where they add context. Identify emotional or comedic turning points '
        'and quote the exact exchange that changes the mood when present in the transcript. '
        'Cover the full arc through the last transcript timestamp and describe how the video '
        'ends visually. Do not duplicate every keyframe line in your answer.'
    )
    return '\n'.join(parts)


@pxt.udf
def assemble_benchmark_context(
    question: str,
    transcript_context: list | None,
    frame_context: list | None,
    vision_label: str = 'Vision',
) -> str:
    return _assemble_benchmark_context_impl(
        question, transcript_context, frame_context, vision_label
    )


def _assemble_mcq_evidence_impl(
    transcript_context: list | None,
    frame_context: list | None,
    vision_label: str = 'Vision',
) -> str:
    """Transcript + keyframe timeline only — no Pursuit essay rubric."""
    parts = ['Evidence for upcoming multiple-choice questions about this video.']
    transcript_lines: list[str] = []
    for item in transcript_context or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        start = float(item.get('segment_start', 0.0))
        if not _is_usable_transcript_chunk(text, start):
            continue
        transcript_lines.append(_format_transcript_line(item))
    transcript_str = (
        '\n'.join(transcript_lines) if transcript_lines else '[no speech detected in audio chunks]'
    )
    parts.append(f'\n<audio_transcript>\n{transcript_str}\n</audio_transcript>')
    frame_lines: list[str] = []
    for item in frame_context or []:
        if not isinstance(item, dict):
            continue
        pos_msec = float(item.get('pos_msec', 0.0))
        segment_start = float(item.get('segment_start', 0.0))
        insight = str(item.get('frame_insight', '')).strip() or '(none)'
        frame_lines.append(
            f'[{pos_msec / 1000.0:.2f}s | segment {segment_start:.1f}s] '
            f'{vision_label}: {insight}'
        )
    frame_str = '\n'.join(frame_lines) if frame_lines else 'N/A'
    parts.append(f'\n<visual_keyframe_timeline>\n{frame_str}\n</visual_keyframe_timeline>')
    return '\n'.join(parts)


@pxt.udf
def assemble_mcq_evidence(
    transcript_context: list | None,
    frame_context: list | None,
    vision_label: str = 'Vision',
) -> str:
    return _assemble_mcq_evidence_impl(transcript_context, frame_context, vision_label)


def _gemini_synthesis_prompt_impl(
    context: str | None,
    video_duration_sec: float | None = None,
) -> str:
    body = (context or '').strip()
    duration_note = ''
    if video_duration_sec and float(video_duration_sec) > 0:
        duration_note = (
            f'The video is approximately {float(video_duration_sec):.0f} seconds long. '
        )
    return (
        f'{duration_note}'
        'Analyze the evidence below and answer the analysis question thoroughly, '
        'as a flowing narrative with causal connections between events. '
        'Use the audio transcript for speakers and dialogue; weave keyframe observations '
        'into the story. Identify emotional or comedic turning points and quote the exact '
        'exchange that changes the mood when present. '
        'Cover the full arc through the last transcript timestamp and describe how the video '
        'ends visually. '
        'Structure with **Main Activities:**, **Speakers:**, and **Visual Events:** sections '
        'when helpful. '
        'Do not produce a per-frame inventory or timestamped bullet log. '
        'Do not mention missing transcripts or data gaps.\n\n'
        f'{body}'
    )


@pxt.udf
def gemini_synthesis_prompt(context: str | None, video_duration_sec: float | None = None) -> str:
    return _gemini_synthesis_prompt_impl(context, video_duration_sec)


def _normalize_insight(text: str) -> str:
    return ' '.join(text.lower().split())


def _dedupe_frame_context_impl(frame_context: list | None) -> list:
    if not frame_context:
        return []
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in frame_context:
        if not isinstance(item, dict):
            continue
        insight = str(item.get('frame_insight', '')).strip()
        key = _normalize_insight(insight)
        if not insight or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


@pxt.udf
def dedupe_frame_context(frame_context: list | None) -> list:
    """Collapse near-duplicate frame insights before synthesis (OSS path)."""
    return _dedupe_frame_context_impl(frame_context)


def _truncate_frame_context_impl(
    frame_context: list | None,
    max_frames: int = 15,
) -> list:
    if not frame_context or len(frame_context) <= max_frames:
        return list(frame_context or [])
    n = len(frame_context)
    if max_frames <= 1:
        return [frame_context[0]]
    indices = {
        round(i * (n - 1) / (max_frames - 1)) for i in range(max_frames)
    }
    return [frame_context[i] for i in sorted(indices)]


def _summarize_frame_context_impl(
    frame_context: list | None,
    max_entries: int = 12,
) -> list:
    deduped = _dedupe_frame_context_impl(frame_context)
    return _truncate_frame_context_impl(deduped, max_entries)


@pxt.udf
def summarize_frame_context(frame_context: list | None, max_entries: int = 12) -> list:
    """Dedupe near-duplicate insights and cap timeline length before synthesis."""
    return _summarize_frame_context_impl(frame_context, max_entries)


def _compact_frame_insight_impl(insight: str, max_chars: int = 120) -> str:
    text = insight.strip()
    if not text:
        return ''
    text = re.sub(
        r'^At (the )?\d+(\.\d+)?(-second)? (mark,?\s*)',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'^At \d+(\.\d+)? seconds?,?\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'^The (keyframe|scene|video) (shows|depicts)\s+',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = ' '.join(text.split())
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(' ', 1)[0]
    return f'{truncated}...'


def _compact_frame_context_impl(
    frame_context: list | None,
    max_chars: int = 120,
) -> list:
    compacted: list[dict] = []
    for item in frame_context or []:
        if not isinstance(item, dict):
            continue
        insight = _compact_frame_insight_impl(
            str(item.get('frame_insight', '')).strip(),
            max_chars,
        )
        if not insight:
            continue
        compacted.append({**item, 'frame_insight': insight})
    return compacted


@pxt.udf
def compact_frame_context(frame_context: list | None, max_chars: int = 120) -> list:
    """Shorten per-frame captions before OSS synthesis to reduce prompt bloat."""
    return _compact_frame_context_impl(frame_context, max_chars)


def _select_scene_frames_impl(
    frame_context: list | None,
    scene_cuts: list | None,
    budget: int,
) -> list:
    frames = sorted(
        (item for item in (frame_context or []) if isinstance(item, dict)),
        key=lambda item: float(item.get('pos_msec', 0.0)),
    )
    if not frames or budget <= 0 or len(frames) <= budget:
        return list(frames)

    scene_starts = sorted(
        {
            float(scene.get('start_time', 0.0))
            for scene in (scene_cuts or [])
            if isinstance(scene, dict)
        }
    )
    selected: list[dict] = []
    used_indices: set[int] = set()

    scene_slots = min(len(scene_starts), max(1, budget // 2))
    if scene_slots >= len(scene_starts):
        chosen_starts = scene_starts
    elif scene_slots <= 1:
        chosen_starts = [scene_starts[0]] if scene_starts else []
    else:
        # Spread scene-aligned slots across the full timeline (not front-loaded).
        chosen_indices = [
            round(i * (len(scene_starts) - 1) / (scene_slots - 1)) for i in range(scene_slots)
        ]
        chosen_starts = [scene_starts[i] for i in chosen_indices]
    for start in chosen_starts:
        target_ms = start * 1000.0
        best_idx = min(
            range(len(frames)),
            key=lambda idx: abs(float(frames[idx].get('pos_msec', 0.0)) - target_ms),
        )
        if best_idx not in used_indices:
            used_indices.add(best_idx)
            selected.append(frames[best_idx])

    remaining = budget - len(selected)
    if remaining > 0:
        n = len(frames)
        if remaining == 1:
            spread_indices = [0]
        else:
            spread_indices = [
                round(i * (n - 1) / (remaining - 1)) for i in range(remaining)
            ]
        for idx in spread_indices:
            if idx in used_indices:
                continue
            used_indices.add(idx)
            selected.append(frames[idx])
            if len(selected) >= budget:
                break
        cursor = 0
        while len(selected) < budget and cursor < n:
            if cursor not in used_indices:
                used_indices.add(cursor)
                selected.append(frames[cursor])
            cursor += 1

    return sorted(selected, key=lambda item: float(item.get('pos_msec', 0.0)))


@pxt.udf
def select_scene_frames(
    frame_context: list | None,
    scene_cuts: list | None,
    budget: int,
) -> list:
    return _select_scene_frames_impl(frame_context, scene_cuts, int(budget or 0))


def _oss_synthesis_prompt_impl(
    context: str | None,
    video_duration_sec: float | None = None,
) -> str:
    body = (context or '').strip()
    duration_note = ''
    if video_duration_sec and float(video_duration_sec) > 0:
        duration_note = (
            f'The video is approximately {float(video_duration_sec):.0f} seconds long. '
        )
    return (
        f'{duration_note}'
        'Analyze the evidence below and answer the analysis question thoroughly. '
        'Use the audio transcript for speakers and quoted dialogue; prefer the transcript when '
        'it disagrees with frame captions. Identify emotional or comedic turning points and '
        'quote the exact exchange that changes the mood when present in the transcript.\n\n'
        'Format your answer like a professional video analyst (match native Gemini quality):\n'
        '**Main Activities:** — numbered list (max 6 items) of what happens, in order\n'
        '**Speakers:** — bullet list mapping speaker labels to roles/names when known\n'
        '**Visual Events:** — bullet list with timestamp ranges '
        '(e.g. 0:00-0:30), not per-frame spam\n\n'
        'Rules: write connected paragraphs under each section; merge duplicate observations; '
        'never repeat the same paragraph twice; never produce a per-frame inventory; '
        'never copy the visual_keyframe_timeline verbatim; cover the full arc through the last '
        'transcript timestamp and describe how the video ends visually before stopping; '
        'stop after completing Visual Events.\n\n'
        f'{body}'
    )


@pxt.udf
def oss_synthesis_prompt(context: str | None, video_duration_sec: float | None = None) -> str:
    return _oss_synthesis_prompt_impl(context, video_duration_sec)


@pxt.udf
def vision_cost_from_frames(frame_context: list | None) -> float:
    if not frame_context:
        return 0.0
    total = 0.0
    for item in frame_context:
        if isinstance(item, dict):
            total += float(item.get('frame_cost', 0.0) or 0.0)
    return total


def _asr_cost_from_transcripts_impl(
    transcript_context: list | None,
    video_duration_sec: float | None,
) -> float:
    duration = float(video_duration_sec or 0.0)
    chunk_duration = 0.0
    output_tokens = 0
    for item in transcript_context or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        output_tokens += max(1, len(text) // 4) if text else 0
        start = float(item.get('segment_start', 0.0))
        end = item.get('segment_end')
        if end is not None:
            chunk_duration += max(0.0, float(end) - start)
    if chunk_duration <= 0.0:
        audio_seconds = duration
    else:
        audio_seconds = min(duration or chunk_duration, chunk_duration)
    if audio_seconds <= 0.0 and chunk_duration > 0.0:
        audio_seconds = chunk_duration
    if audio_seconds > 0:
        input_tokens = max(1, int(audio_seconds * GEMINI_AUDIO_TOKENS_PER_SEC))
    else:
        input_tokens = 0
    return _compute_cost_impl(input_tokens, output_tokens, GEMINI_25_FLASH_INPUT_PER_M)


@pxt.udf
def asr_cost_from_transcripts(
    transcript_context: list | None,
    video_duration_sec: float | None,
) -> float:
    return _asr_cost_from_transcripts_impl(transcript_context, video_duration_sec)


@pxt.udf
def vision_rollup_from_frames(frame_context: list | None, vision_label: str = 'Gemini') -> dict:
    rows = frame_context or []
    lines: list[str] = []
    total_cost = 0.0
    for item in sorted(
        (r for r in rows if isinstance(r, dict)),
        key=lambda r: float(r.get('pos_msec', 0.0)),
    ):
        pos_msec = float(item.get('pos_msec', 0.0))
        segment_start = float(item.get('segment_start', 0.0))
        insight = str(item.get('frame_insight', '')).strip() or '(none)'
        total_cost += float(item.get('frame_cost', 0.0) or 0.0)
        lines.append(
            f'[{pos_msec / 1000.0:.2f}s | segment {segment_start:.1f}s] '
            f'{vision_label}: {insight}'
        )
    return {'text': '\n'.join(lines), 'total_frame_cost': total_cost, 'frame_count': len(lines)}


@pxt.udf
def gemini_orchestrated_cost(vision_cost: float, asr_cost: float, synthesis_cost: float) -> float:
    return float(vision_cost or 0.0) + float(asr_cost or 0.0) + float(synthesis_cost or 0.0)


@pxt.udf
def cost_delta(native_cost: float | None, orchestrated: float | None) -> float:
    return float(native_cost or 0.0) - float(orchestrated or 0.0)


def _time_window_segment_times_impl(duration: float, window_sec: float = 10.0) -> list[float]:
    if duration <= window_sec:
        return []
    times: list[float] = []
    t = window_sec
    while t < duration - 1e-3:
        times.append(round(t, 3))
        t += window_sec
    return times


def _scene_cut_segment_times_impl(
    scene_cuts: list | None,
    video_duration_sec: float | None,
    *,
    min_scene_duration: float = 1.0,
    fallback_window_sec: float = 10.0,
) -> list[float]:
    """Split points for video_splitter: scene boundaries, or fixed windows if detection fails."""
    duration = float(video_duration_sec or 0.0)
    if duration <= 0:
        return []

    scenes = [s for s in (scene_cuts or []) if isinstance(s, dict)]
    if len(scenes) == 1:
        return []
    if len(scenes) >= 2:
        starts = sorted({round(float(s.get('start_time', 0.0)), 3) for s in scenes})
        split_times = [
            t
            for t in starts
            if min_scene_duration < t < duration - min_scene_duration
        ]
        if split_times:
            return split_times

    return _time_window_segment_times_impl(duration, fallback_window_sec)


@pxt.udf
def scene_cut_segment_times(
    scene_cuts: pxt.Json,
    video_duration_sec: float,
    min_scene_duration: float,
    fallback_window_sec: float,
) -> list[float]:
    return _scene_cut_segment_times_impl(
        scene_cuts,
        video_duration_sec,
        min_scene_duration=min_scene_duration,
        fallback_window_sec=fallback_window_sec,
    )


# --- Path 2 multimodal synthesis ---

def _gemini_multimodal_synthesis_contents_impl(
    prompt: str | None,
    frame_context: list | None,
    frame_images: list | None,
    max_images: int = 8,
) -> list:
    """Build generate_content contents: text prompt + up to K keyframe images.

    `frame_context` is the summarized text timeline (pos_msec keys).
    `frame_images` is a separate query result with {pos_msec, frame}.
    """
    contents: list = [str(prompt or '')]
    limit = max(0, int(max_images or 0))
    if limit <= 0:
        return contents

    by_pos: dict[float, object] = {}
    for item in frame_images or []:
        if not isinstance(item, dict):
            continue
        frame = item.get('frame')
        if frame is None:
            continue
        by_pos[float(item.get('pos_msec', 0.0))] = frame

    count = 0
    for item in frame_context or []:
        if count >= limit:
            break
        if not isinstance(item, dict):
            continue
        pos = float(item.get('pos_msec', 0.0))
        frame = by_pos.get(pos)
        if frame is None and by_pos:
            # Nearest timestamp match (float drift).
            nearest = min(by_pos.keys(), key=lambda p: abs(p - pos))
            if abs(nearest - pos) <= 1.0:
                frame = by_pos[nearest]
        if frame is None:
            continue
        contents.append(frame)
        count += 1
    return contents


@pxt.udf
def gemini_multimodal_synthesis_contents(
    prompt: str | None,
    frame_context: list | None,
    frame_images: list | None,
    max_images: int = 8,
) -> list:
    return _gemini_multimodal_synthesis_contents_impl(
        prompt, frame_context, frame_images, max_images
    )


# --- Path 4 Native fal ---

FAL_VIDEO_UNDERSTANDING_APP = 'fal-ai/video-understanding'
FAL_USD_PER_5_SEC = 0.01
# fal-ai/video-understanding rejects clips longer than ~122s.
FAL_MAX_DURATION_SEC_DEFAULT = 120.0


def _ensure_fal_key() -> None:
    if not os.environ.get('FAL_KEY') and os.environ.get('FAL_API_KEY'):
        os.environ['FAL_KEY'] = os.environ['FAL_API_KEY']


def _probe_duration_sec(path: str) -> float | None:
    try:
        import av

        with av.open(path) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
            for stream in container.streams.video:
                if stream.duration is not None and stream.time_base is not None:
                    return float(stream.duration * stream.time_base)
    except Exception:
        return None
    return None


def _trim_video_for_fal(path: str, max_duration_sec: float) -> str:
    """Return path to a clip truncated to max_duration_sec (temp file if trimmed)."""
    import subprocess
    import tempfile

    duration = _probe_duration_sec(path)
    if duration is None or duration <= max_duration_sec + 0.5:
        return path
    out = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    out.close()
    # Re-encode short prefix so audio/video stay in sync for fal.
    cmd = [
        'ffmpeg',
        '-y',
        '-i',
        path,
        '-t',
        f'{max_duration_sec:.3f}',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '23',
        '-c:a',
        'aac',
        '-movflags',
        '+faststart',
        out.name,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out.name


def _resolve_fal_video_url_impl(
    video: str | None,
    override_url: str | None = None,
    max_duration_sec: float = FAL_MAX_DURATION_SEC_DEFAULT,
) -> str:
    override = (override_url or '').strip()
    if override:
        return override
    path = str(video or '').strip()
    if path.startswith(('http://', 'https://')):
        return path
    if not path or not Path(path).exists():
        raise FileNotFoundError(f'fal video path not found: {path!r}')
    _ensure_fal_key()
    upload_path = _trim_video_for_fal(path, float(max_duration_sec or FAL_MAX_DURATION_SEC_DEFAULT))
    import fal_client

    try:
        return fal_client.upload_file(upload_path)
    finally:
        if upload_path != path:
            try:
                Path(upload_path).unlink(missing_ok=True)
            except OSError:
                pass


@pxt.udf(is_deterministic=False)
def resolve_fal_video_url(
    video: pxt.Video,
    override_url: str = '',
    max_duration_sec: float = FAL_MAX_DURATION_SEC_DEFAULT,
) -> str:
    return _resolve_fal_video_url_impl(video, override_url or None, max_duration_sec)


def _fal_video_understanding_input_impl(
    video_url: str,
    prompt: str,
    detailed_analysis: bool = False,
) -> dict:
    return {
        'video_url': str(video_url or ''),
        'prompt': str(prompt or ''),
        'detailed_analysis': bool(detailed_analysis),
    }


@pxt.udf
def fal_video_understanding_input(
    video_url: str,
    prompt: str,
    detailed_analysis: bool = False,
) -> dict:
    return _fal_video_understanding_input_impl(video_url, prompt, detailed_analysis)


def _fal_run_safe_impl(input_args: dict | None, app: str = FAL_VIDEO_UNDERSTANDING_APP) -> dict:
    """Call fal.subscribe; return error payload instead of raising (keeps other paths alive)."""
    _ensure_fal_key()
    try:
        import fal_client

        result = fal_client.subscribe(app, arguments=dict(input_args or {}))
        if isinstance(result, dict):
            return result
        return {'output': str(result)}
    except Exception as exc:  # noqa: BLE001 — soft-fail Path 4 only
        return {'output': '', 'error': f'{type(exc).__name__}: {exc}'}


@pxt.udf(is_deterministic=False)
def fal_run_safe(input_args: dict, app: str = FAL_VIDEO_UNDERSTANDING_APP) -> dict:
    return _fal_run_safe_impl(input_args, app)


def _fal_text_impl(response: pxt.Json) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response or '').strip()
    err = response.get('error')
    if err and not response.get('output'):
        return f'[fal error] {err}'
    output = response.get('output')
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, dict) and output.get('text'):
        return str(output['text']).strip()
    return ''


@pxt.udf
def fal_text(response: pxt.Json) -> str:
    return _fal_text_impl(response)


def _fal_video_cost_impl(
    duration_sec: float | None,
    max_duration_sec: float = FAL_MAX_DURATION_SEC_DEFAULT,
) -> float:
    duration = max(0.0, float(duration_sec or 0.0))
    if max_duration_sec and max_duration_sec > 0:
        duration = min(duration, float(max_duration_sec))
    if duration <= 0:
        return 0.0
    chunks = max(1, math.ceil(duration / 5.0))
    return float(chunks * FAL_USD_PER_5_SEC)


@pxt.udf
def fal_video_cost(
    duration_sec: float | None,
    max_duration_sec: float = FAL_MAX_DURATION_SEC_DEFAULT,
) -> float:
    return _fal_video_cost_impl(duration_sec, max_duration_sec)


# --- Path 5 Native Nova (Bedrock) ---

NOVA_TOKENS_PER_FRAME = 288
NOVA_LITE_INPUT_PER_M = 0.06
NOVA_LITE_OUTPUT_PER_M = 0.24
NOVA_PRO_INPUT_PER_M = 0.80
NOVA_PRO_OUTPUT_PER_M = 3.20


def _nova_rates_for_model(model_id: str) -> tuple[float, float]:
    mid = (model_id or '').lower()
    if 'nova-pro' in mid or 'nova-premier' in mid:
        return NOVA_PRO_INPUT_PER_M, NOVA_PRO_OUTPUT_PER_M
    return NOVA_LITE_INPUT_PER_M, NOVA_LITE_OUTPUT_PER_M


def _estimate_nova_video_tokens_impl(duration_sec: float | None, query: str | None = None) -> int:
    """Nova Lite/Pro: 1 FPS up to 16 min (~288 tokens/frame)."""
    duration = max(0.0, float(duration_sec or 0.0))
    frames = min(960, max(1, int(math.ceil(duration)))) if duration > 0 else 0
    video_tokens = frames * NOVA_TOKENS_PER_FRAME
    query_tokens = max(1, len(query or '') // 4) if query else 0
    return video_tokens + query_tokens + _NATIVE_PROMPT_OVERHEAD_TOKENS


@pxt.udf
def estimate_nova_video_tokens(duration_sec: float | None, query: str) -> int:
    return _estimate_nova_video_tokens_impl(duration_sec, query)


def _nova_text_impl(response: pxt.Json) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response or '').strip()
    err = response.get('error')
    if err and not (
        (isinstance(response.get('output'), dict) and response['output'].get('message'))
        or response.get('content')
        or response.get('completion')
    ):
        return f'[nova error] {err}'
    # InvokeModel / Converse-shaped responses
    output = response.get('output')
    if isinstance(output, dict):
        message = output.get('message') or {}
        if isinstance(message, dict):
            parts = message.get('content') or []
            texts = [
                str(part['text'])
                for part in parts
                if isinstance(part, dict) and part.get('text')
            ]
            if texts:
                return '\n'.join(texts).strip()
    content = response.get('content')
    if isinstance(content, list):
        texts = [
            str(part['text']) for part in content if isinstance(part, dict) and part.get('text')
        ]
        if texts:
            return '\n'.join(texts).strip()
    if response.get('completion'):
        return str(response['completion']).strip()
    return ''


@pxt.udf
def nova_text(response: pxt.Json) -> str:
    return _nova_text_impl(response)


def _nova_invoke_safe_impl(
    video: str | None,
    prompt: str,
    model_id: str,
    s3_uri: str = '',
) -> dict:
    """Call Bedrock Converse with Nova video; soft-fail so other paths still run."""
    try:
        import boto3

        region = (
            os.environ.get('AWS_DEFAULT_REGION')
            or os.environ.get('AWS_REGION')
            or os.environ.get('BEDROCK_REGION_NAME')
            or 'us-east-1'
        )
        client = boto3.client('bedrock-runtime', region_name=region)
        if (s3_uri or '').strip():
            video_block = {
                'format': 'mp4',
                'source': {'s3Location': {'uri': s3_uri.strip()}},
            }
        else:
            path = str(video or '').strip()
            if not path or not Path(path).exists():
                raise FileNotFoundError(f'nova video path not found: {path!r}')
            video_block = {
                'format': 'mp4',
                'source': {'bytes': Path(path).read_bytes()},
            }
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {'video': video_block},
                        {'text': str(prompt or '')},
                    ],
                }
            ],
        )
        # boto3 returns a plain dict-like response
        return dict(response)
    except Exception as exc:  # noqa: BLE001 — soft-fail Path 5 only
        return {'output': {}, 'error': f'{type(exc).__name__}: {exc}'}


@pxt.udf(is_deterministic=False)
def nova_invoke_safe(
    video: pxt.Video,
    prompt: str,
    model_id: str,
    s3_uri: str = '',
) -> dict:
    return _nova_invoke_safe_impl(video, prompt, model_id, s3_uri)


def _nova_usage_tokens_impl(response: pxt.Json) -> tuple[int, int]:
    if not isinstance(response, dict):
        return 0, 0
    usage = response.get('usage') or {}
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(
        usage.get('inputTokens', 0)
        or usage.get('input_tokens', 0)
        or usage.get('promptTokens', 0)
        or 0
    )
    output = int(
        usage.get('outputTokens', 0)
        or usage.get('output_tokens', 0)
        or usage.get('completionTokens', 0)
        or 0
    )
    return prompt, output


@pxt.udf
def nova_prompt_tokens(response: pxt.Json) -> int:
    return _nova_usage_tokens_impl(response)[0]


@pxt.udf
def nova_output_tokens(response: pxt.Json) -> int:
    return _nova_usage_tokens_impl(response)[1]


def _nova_cost_impl(
    actual_input_tokens: int,
    actual_output_tokens: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    model_id: str,
    input_rate_override: float | None = None,
    output_rate_override: float | None = None,
) -> float:
    default_in, default_out = _nova_rates_for_model(model_id)
    rate_in = float(input_rate_override) if input_rate_override is not None else default_in
    rate_out = float(output_rate_override) if output_rate_override is not None else default_out
    if int(actual_input_tokens or 0) + int(actual_output_tokens or 0) > 0:
        inp, out = int(actual_input_tokens or 0), int(actual_output_tokens or 0)
    else:
        inp, out = int(estimated_input_tokens or 0), int(estimated_output_tokens or 0)
    return float(inp) * rate_in / 1_000_000 + float(out) * rate_out / 1_000_000


@pxt.udf
def nova_cost(
    actual_input_tokens: int,
    actual_output_tokens: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    model_id: str,
    input_rate_per_m: float = -1.0,
    output_rate_per_m: float = -1.0,
) -> float:
    in_override = None if float(input_rate_per_m) < 0 else float(input_rate_per_m)
    out_override = None if float(output_rate_per_m) < 0 else float(output_rate_per_m)
    return _nova_cost_impl(
        actual_input_tokens,
        actual_output_tokens,
        estimated_input_tokens,
        estimated_output_tokens,
        model_id,
        in_override,
        out_override,
    )

