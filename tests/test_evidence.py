"""Transcript parsing, frame selection, and synthesis request assembly."""

from __future__ import annotations

import PIL.Image

from video_benchmark.evidence import (
    asr_segment_lines_impl,
    attached_frames_impl,
    compact_caption_impl,
    dedupe_frames_impl,
    evidence_text_impl,
    merge_transcript_rows_impl,
    parse_diarized_transcript_impl,
    select_scene_frames_impl,
    synthesis_contents_impl,
    transcript_text_impl,
)


def _frames(n: int, spacing: float = 10.0) -> list[dict]:
    return [{'position_sec': i * spacing, 'caption': f'frame {i}'} for i in range(n)]


def test_parse_diarized_transcript():
    text = '[00:05] Speaker 1: Hi.\ncontinued line\n[1:02:03] SPEAKER_02: Bye.'
    lines = parse_diarized_transcript_impl(text, offset_sec=100.0)
    assert [line['start'] for line in lines] == [105.0, 100.0 + 3723.0]
    assert lines[0] == {
        'start': 105.0,
        'end': 105.0,
        'text': 'Hi. continued line',
        'speaker': 'Speaker 1',
    }
    assert lines[1]['speaker'] == 'SPEAKER_02'


def test_asr_segment_lines_whisperx_and_whisper():
    diarized = {
        'segments': [{'start': 1.0, 'end': 2.0, 'text': ' Hello ', 'speaker': 'SPEAKER_00'}]
    }
    assert asr_segment_lines_impl(diarized, 10.0) == [
        {'start': 11.0, 'end': 12.0, 'text': 'Hello', 'speaker': 'SPEAKER_00'}
    ]
    assert asr_segment_lines_impl({'text': 'only text'}, 0.0)[0]['text'] == 'only text'


def test_merge_and_render_transcript():
    rows = [{'lines': [{'start': 9.0, 'text': 'b'}]}, {'lines': [{'start': 1.0, 'text': 'a'}]}, {}]
    merged = merge_transcript_rows_impl(rows)
    assert [line['text'] for line in merged] == ['a', 'b']
    rendered = transcript_text_impl(
        [
            {'start': 0.5, 'text': 'Hi', 'speaker': 'Speaker 1'},
            {'start': 1.0, 'text': 'Transcribe this audio'},
        ]
    )
    # Short early lines are kept; only the model echoing its instructions is dropped.
    assert rendered == '[0.5s] Speaker 1: Hi'
    assert transcript_text_impl([]) == '[no speech detected]'


def test_dedupe_drops_empty_and_repeated_captions():
    frames = [
        {'position_sec': 2.0, 'caption': 'A  man   talks'},
        {'position_sec': 1.0, 'caption': 'a man talks'},
        {'position_sec': 3.0, 'caption': ''},
    ]
    assert [f['position_sec'] for f in dedupe_frames_impl(frames)] == [1.0]


def test_select_keeps_budget_near_cuts_and_spread():
    frames = _frames(24)
    cuts = [{'start_time': t} for t in (0.0, 55.0, 118.0, 181.0, 222.0)]
    selected = select_scene_frames_impl(frames, cuts, budget=8)
    # Half the budget: frames nearest to 4 of the 5 scene starts (spread: 0, 55, 181, 222 s);
    # the rest spread evenly, filling from the start when they collide.
    assert [f['position_sec'] for f in selected] == [0, 10, 50, 80, 150, 180, 220, 230]


def test_select_without_cuts_spreads_evenly():
    selected = select_scene_frames_impl(_frames(24), [], budget=4)
    assert [f['position_sec'] for f in selected] == [0.0, 80.0, 150.0, 230.0]
    assert len(select_scene_frames_impl(_frames(3), [], budget=16)) == 3


def test_compact_caption():
    assert compact_caption_impl('At the 12.5-second mark, a man waves.', 120) == 'a man waves.'
    assert compact_caption_impl('The keyframe shows ' + 'word ' * 50, 20).endswith('...')


def test_attached_frames_span_the_selection():
    selected = _frames(16)
    attached = attached_frames_impl(selected, 4)
    assert [f['position_sec'] for f in attached] == [0.0, 50.0, 100.0, 150.0]
    assert attached_frames_impl(selected, 0) == []


def test_synthesis_contents_labels_images_then_prompt():
    image = PIL.Image.new('RGB', (4, 4))
    images = [{'position_sec': 0.0, 'frame': image}, {'position_sec': 10.0, 'frame': image}]
    contents = synthesis_contents_impl('PROMPT', [{'position_sec': 10.0}], images)
    assert contents == ['Keyframe at 10.0s:', image, 'PROMPT']


def test_evidence_text_blocks():
    text = evidence_text_impl(
        [{'start': 1.0, 'text': 'hello'}], [{'position_sec': 2.0, 'caption': 'a room'}], 'Gemini'
    )
    assert '<audio_transcript>\n[1.0s] hello\n</audio_transcript>' in text
    assert '[2.0s] Gemini: a room' in text
