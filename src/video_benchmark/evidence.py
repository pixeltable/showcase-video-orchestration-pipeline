"""Evidence for the orchestrated paths: transcript lines, keyframe captions, and the
selection and formatting that turn them into a synthesis request.

Transcript line: {'start': s, 'end': s, 'text': str, 'speaker'?: str}
Frame row:       {'position_sec': s, 'caption': str, ...}
"""

from __future__ import annotations

import math
import re

import pixeltable as pxt

_TRANSCRIPT_LINE = re.compile(
    r'^\s*\[(?P<ts>[^\]]+)\]\s*(?:(?P<speaker>Speaker\s*\d+|SPEAKER_\d+):\s*)?(?P<body>.+)\s*$',
    re.IGNORECASE,
)


def _parse_timestamp_sec(token: str) -> float | None:
    cleaned = token.strip().strip('[]').removesuffix('s')
    try:
        parts = [float(p) for p in cleaned.split(':')]
    except ValueError:
        return None
    if len(parts) > 3:
        return None
    seconds = 0.0
    for part in parts:
        if not math.isfinite(part) or part < 0:
            return None
        seconds = seconds * 60.0 + part
    return seconds


def parse_diarized_transcript_impl(text: str, offset_sec: float = 0.0) -> list[dict]:
    """Parse '[mm:ss] Speaker N: text' lines. Unstamped lines continue the previous line."""
    lines: list[dict] = []
    for raw_line in (text or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TRANSCRIPT_LINE.match(line)
        if match:
            ts = _parse_timestamp_sec(match.group('ts'))
            start = offset_sec + (ts or 0.0)
            entry = {'start': start, 'end': start, 'text': match.group('body').strip()}
            if ts is None:
                entry['timestamp_status'] = 'invalid'
            if match.group('speaker'):
                entry['speaker'] = match.group('speaker').strip()
            lines.append(entry)
        elif lines:
            lines[-1]['text'] = f'{lines[-1]["text"]} {line}'
        else:
            lines.append({'start': offset_sec, 'end': offset_sec, 'text': line})
    return lines


def asr_segment_lines_impl(result: dict, offset_sec: float = 0.0) -> list[dict]:
    """Lines from a Whisper or WhisperX result (WhisperX segments also carry `speaker`)."""
    lines: list[dict] = []
    for seg in result.get('segments') or []:
        text = str(seg.get('text') or '').strip()
        if not text:
            continue
        start = offset_sec + float(seg.get('start') or 0.0)
        entry = {'start': start, 'end': offset_sec + float(seg.get('end') or 0.0), 'text': text}
        if seg.get('speaker'):
            entry['speaker'] = str(seg['speaker'])
        lines.append(entry)
    if not lines and str(result.get('text') or '').strip():
        lines.append({'start': offset_sec, 'end': offset_sec, 'text': str(result['text']).strip()})
    return lines


def merge_transcript_rows_impl(rows: list) -> list[dict]:
    """Flatten per-chunk `lines` from an audio_chunks query into one time-ordered transcript."""
    merged = [line for row in rows for line in (row.get('lines') or [])]
    return sorted(merged, key=lambda line: float(line['start']))


def _usable_line(line: dict) -> bool:
    text = str(line.get('text') or '').strip()
    # Drop a transcription model echoing its own instructions.
    return (
        bool(text)
        and line.get('timestamp_status') != 'invalid'
        and not text.lower().startswith('transcribe this audio')
    )


def transcript_text_impl(lines: list) -> str:
    rendered = []
    for line in lines:
        if not _usable_line(line):
            continue
        speaker = f'{line["speaker"]}: ' if line.get('speaker') else ''
        rendered.append(f'[{float(line["start"]):.1f}s] {speaker}{str(line["text"]).strip()}')
    return (
        '\n'.join(rendered)
        if rendered
        else '[transcription unavailable or empty; speech status unknown]'
    )


def _normalized(text: str) -> str:
    return ' '.join(text.lower().split())


def dedupe_frames_impl(frames: list) -> list[dict]:
    """Drop frames with an empty caption or one identical (after normalizing) to an earlier one."""
    seen: set[str] = set()
    kept: list[dict] = []
    for frame in sorted(frames, key=lambda f: float(f['position_sec'])):
        key = _normalized(str(frame.get('caption') or ''))
        if key and key not in seen:
            seen.add(key)
            kept.append(frame)
    return kept


def select_scene_frames_impl(frames: list, scene_cuts: list, budget: int) -> list[dict]:
    """Keep `budget` frames: up to half nearest to scene starts (spread over the timeline),
    the rest evenly spaced. Frames arrive sampled evenly, so both halves cover the whole video.
    """
    ordered = sorted(frames, key=lambda f: float(f['position_sec']))
    if budget <= 0 or len(ordered) <= budget:
        return ordered
    scene_starts = sorted({float(scene['start_time']) for scene in scene_cuts or []})
    slots = min(len(scene_starts), max(1, budget // 2))
    if slots >= len(scene_starts):
        chosen_starts = scene_starts
    elif slots == 1:
        chosen_starts = scene_starts[:1]
    else:
        chosen_starts = [
            scene_starts[round(i * (len(scene_starts) - 1) / (slots - 1))] for i in range(slots)
        ]
    used: set[int] = set()
    for start in chosen_starts:
        nearest = min(
            range(len(ordered)), key=lambda i: abs(float(ordered[i]['position_sec']) - start)
        )
        used.add(nearest)
    remaining = budget - len(used)
    if remaining > 0:
        n = len(ordered)
        spread = (
            [0]
            if remaining == 1
            else [round(i * (n - 1) / (remaining - 1)) for i in range(remaining)]
        )
        for idx in spread:
            if len(used) >= budget:
                break
            used.add(idx)
        for idx in range(n):
            if len(used) >= budget:
                break
            used.add(idx)
    return [ordered[i] for i in sorted(used)]


def compact_caption_impl(caption: str, max_chars: int) -> str:
    """Shorten a local-VLM caption: drop 'At 12s, the keyframe shows' openers, cap length."""
    text = re.sub(
        r'^At (the )?\d+(\.\d+)?(-second| seconds?)? ?(mark)?,?\s*',
        '',
        caption.strip(),
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'^The (keyframe|scene|video|image) (shows|depicts)\s+', '', text, flags=re.IGNORECASE
    )
    text = ' '.join(text.split())
    if len(text) <= max_chars:
        return text
    return f'{text[:max_chars].rsplit(" ", 1)[0]}...'


def compact_frames_impl(frames: list, max_chars: int) -> list[dict]:
    compacted = []
    for frame in frames:
        caption = compact_caption_impl(str(frame.get('caption') or ''), max_chars)
        if caption:
            compacted.append({**frame, 'caption': caption})
    return compacted


def frame_timeline_impl(frames: list, label: str) -> str:
    rendered = [
        f'[{float(f["position_sec"]):.1f}s] {label}: {str(f.get("caption") or "").strip()}'
        for f in frames
    ]
    return '\n'.join(rendered) if rendered else '[no keyframes]'


def evidence_text_impl(transcript_lines: list, frames: list, label: str) -> str:
    return (
        f'<audio_transcript>\n{transcript_text_impl(transcript_lines)}\n</audio_transcript>\n\n'
        f'<visual_keyframe_timeline>\n{frame_timeline_impl(frames, label)}\n'
        '</visual_keyframe_timeline>'
    )


def attached_frames_impl(selected: list, max_images: int) -> list[dict]:
    """The selected frames whose images go into the synthesis call, spread over the timeline."""
    if max_images <= 0 or not selected:
        return []
    if len(selected) <= max_images:
        return list(selected)
    n = len(selected)
    picks = (
        [0]
        if max_images == 1
        else [round(i * (n - 1) / (max_images - 1)) for i in range(max_images)]
    )
    return [selected[i] for i in sorted(set(picks))]


def synthesis_contents_impl(prompt: str, attached: list, images: list) -> list:
    """generate_content contents: each attached keyframe image labelled with its time, then the
    prompt. `images` rows are {position_sec, frame}; positions come from the same column as the
    selected frames, so they match exactly.
    """
    by_position = {float(row['position_sec']): row['frame'] for row in images}
    contents: list = []
    for frame in attached:
        image = by_position.get(float(frame['position_sec']))
        if image is not None:
            contents.extend([f'Keyframe at {float(frame["position_sec"]):.1f}s:', image])
    contents.append(prompt)
    return contents


@pxt.udf
def parse_diarized_transcript(text: str, offset_sec: float) -> list:
    return parse_diarized_transcript_impl(text, offset_sec)


@pxt.udf
def asr_segment_lines(result: dict, offset_sec: float) -> list:
    return asr_segment_lines_impl(result, offset_sec)


@pxt.udf
def merge_transcript_rows(rows: list) -> list:
    return merge_transcript_rows_impl(rows)


@pxt.udf
def select_frames(frames: list, scene_cuts: list, budget: int) -> list:
    """Dedupe captions, then keep a scene-aware, timeline-spread subset."""
    return select_scene_frames_impl(dedupe_frames_impl(frames), scene_cuts, budget)


@pxt.udf
def compact_frames(frames: list, max_chars: int) -> list:
    return compact_frames_impl(frames, max_chars)


@pxt.udf
def evidence_text(transcript_lines: list, frames: list, label: str) -> str:
    return evidence_text_impl(transcript_lines, frames, label)


@pxt.udf
def attached_frames(selected: list, max_images: int) -> list:
    return attached_frames_impl(selected, max_images)


@pxt.udf
def synthesis_contents(prompt: str, attached: list, images: list) -> list:
    return synthesis_contents_impl(prompt, attached, images)
