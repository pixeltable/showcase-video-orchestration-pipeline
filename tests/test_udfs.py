"""Tests for benchmark UDF implementations."""

from video_benchmark.udfs import (
    GEMINI_AUDIO_TOKENS_PER_SEC,
    _asr_cost_from_transcripts_impl,
    _assemble_benchmark_context_impl,
    _compact_frame_context_impl,
    _compact_frame_insight_impl,
    _compute_cost_impl,
    _dedupe_frame_context_impl,
    _estimate_text_tokens_impl,
    _extract_whisperx_segments_impl,
    _frame_prompt_impl,
    _gemini_synthesis_prompt_impl,
    _gemini_text_impl,
    _gemini_usage_tokens_impl,
    _is_usable_transcript_chunk,
    _llama_response_text_impl,
    _merge_transcript_segment_lists_impl,
    _native_prompt_impl,
    _oss_synthesis_prompt_impl,
    _parse_diarized_transcript_impl,
    _resolved_gemini_cost_impl,
    _scene_cut_segment_times_impl,
    _select_scene_frames_impl,
    _summarize_frame_context_impl,
    _time_window_segment_times_impl,
    _truncate_frame_context_impl,
)


def test_gemini_text_extracts_candidate():
    response = {
        'candidates': [{'content': {'parts': [{'text': 'Hello world'}]}}],
    }
    assert _gemini_text_impl(response) == 'Hello world'


def test_llama_response_text_extracts_choice():
    response = {'choices': [{'message': {'content': 'Answer B'}}]}
    assert _llama_response_text_impl(response) == 'Answer B'


def test_compute_cost():
    cost = _compute_cost_impl(1_000_000, 1_000_000, 1.50)
    assert abs(cost - 3.0) < 0.001


def test_estimate_text_tokens_empty():
    assert _estimate_text_tokens_impl('') == 0


def test_native_prompt_includes_query():
    assert 'interview scene' in _native_prompt_impl('Describe the interview scene')


def test_assemble_benchmark_context_includes_question():
    ctx = _assemble_benchmark_context_impl(
        'What happens?',
        [{'segment_start': 0.0, 'text': 'hello'}],
        [{'pos_msec': 1000.0, 'segment_start': 0.0, 'frame_insight': 'a man'}],
        'OSS-VLM',
    )
    assert 'What happens?' in ctx
    assert 'OSS-VLM' in ctx
    assert ctx.index('<audio_transcript>') < ctx.index('<visual_keyframe_timeline>')
    assert 'cohesive chronological summary' in ctx
    assert '**Main Activities:**' in ctx
    assert '**Speakers:**' in ctx
    assert '**Visual Events:**' in ctx
    assert 'last transcript timestamp' in ctx
    assert 'agreements, conflicts, and gaps' not in ctx.lower()


def test_assemble_benchmark_context_filters_empty_transcripts():
    empty = [{'segment_start': 0.0, 'text': '  '}]
    ctx = _assemble_benchmark_context_impl('Q?', empty, [], 'Gemini')
    assert '[no speech detected in audio chunks]' in ctx


def test_assemble_benchmark_context_filters_prompt_echo():
    junk = [
        {'segment_start': 0.0, 'text': 'Transcribe this audio accurately.'},
        {'segment_start': 10.0, 'text': 'Chris Gardner says hello.'},
    ]
    ctx = _assemble_benchmark_context_impl('Q?', junk, [], 'Gemini')
    assert 'Transcribe this audio' not in ctx
    assert 'Chris Gardner' in ctx


def test_is_usable_transcript_chunk_rejects_short_opening():
    assert not _is_usable_transcript_chunk('Pastor Sir', 0.0)
    assert _is_usable_transcript_chunk('Chris Gardner? Good morning.', 10.0)


def test_gemini_synthesis_prompt_includes_guidance():
    prompt = _gemini_synthesis_prompt_impl('ANALYSIS QUESTION: test', 255.0)
    assert 'flowing narrative' in prompt
    assert 'per-frame inventory' in prompt
    assert '255 seconds' in prompt
    assert 'turning points' in prompt
    assert 'last transcript timestamp' in prompt
    assert '**Main Activities:**' in prompt
    assert 'ANALYSIS QUESTION: test' in prompt


def test_oss_synthesis_prompt_requests_native_sections():
    prompt = _oss_synthesis_prompt_impl('ANALYSIS QUESTION: test', 255.0)
    assert '**Main Activities:**' in prompt
    assert '**Speakers:**' in prompt
    assert '**Visual Events:**' in prompt
    assert 'never repeat the same paragraph twice' in prompt
    assert 'last transcript timestamp' in prompt
    assert 'elevator' not in prompt.lower()
    assert 'tonight' not in prompt.lower()
    assert '255 seconds' in prompt


def test_gemini_usage_tokens_ignores_total_token_count():
    response = {
        'usageMetadata': {
            'promptTokenCount': 100,
            'totalTokenCount': 999,
        },
    }
    assert _gemini_usage_tokens_impl(response) == (100, 0)


def test_compact_frame_insight_strips_timestamp_prefix():
    raw = (
        'At the 10.8-second mark, the scene shows a man in a grey jacket '
        'seated at a conference table in a professional setting.'
    )
    compact = _compact_frame_insight_impl(raw, max_chars=120)
    assert '10.8-second' not in compact
    assert 'grey jacket' in compact
    assert len(compact) <= 123


def test_compact_frame_context_shortens_entries():
    frames = [
        {
            'pos_msec': 0.0,
            'segment_start': 0.0,
            'frame_insight': (
                'At 0.0 seconds, the scene shows a man with a serious expression in a busy office '
                'with green digital displays and many people in the background.'
            ),
        },
        {
            'pos_msec': 10000.0,
            'segment_start': 0.0,
            'frame_insight': (
                'Five men in suits around a boardroom table overlooking a city skyline.'
            ),
        },
    ]
    compacted = _compact_frame_context_impl(frames, max_chars=80)
    assert len(compacted) == 2
    assert all(len(item['frame_insight']) <= 83 for item in compacted)


def test_frame_prompt_includes_expressions_and_timestamp():
    prompt = _frame_prompt_impl('What happens?', 42.5)
    assert '42.5s' in prompt
    assert 'laughter' in prompt


def test_parse_diarized_transcript_splits_lines():
    text = '[0:42] Speaker 1: What were you doing?\n[0:45] Speaker 2: Painting.'
    lines = _parse_diarized_transcript_impl(text, chunk_offset_sec=10.0)
    assert len(lines) == 2
    assert lines[0]['speaker'] == 'Speaker 1'
    assert abs(lines[0]['segment_start'] - 52.0) < 0.01
    assert 'Painting' in lines[1]['text']


def test_extract_whisperx_segments_with_offset():
    diarized = {
        'segments': [
            {'start': 1.0, 'end': 2.0, 'text': 'hello', 'speaker': 'SPEAKER_00'},
            {'start': 2.5, 'end': 3.0, 'text': 'world', 'speaker': 'SPEAKER_01'},
        ]
    }
    lines = _extract_whisperx_segments_impl(diarized, chunk_offset_sec=10.0)
    assert len(lines) == 2
    assert lines[0]['segment_start'] == 11.0
    assert lines[0]['speaker'] == 'SPEAKER_00'


def test_merge_transcript_segment_lists_flattens_rows():
    rows = [
        {
            'segment_lines': [
                {'segment_start': 0.0, 'text': 'a', 'speaker': 'Speaker 1'},
                {'segment_start': 1.0, 'text': 'b', 'speaker': 'Speaker 2'},
            ]
        }
    ]
    merged = _merge_transcript_segment_lists_impl(rows)
    assert len(merged) == 2
    assert merged[0]['speaker'] == 'Speaker 1'


def test_select_scene_frames_spreads_across_timeline():
    frames = [
        {'pos_msec': float(i * 10000), 'frame_insight': str(i)} for i in range(10)
    ]
    # Many early scenes + one late scene — old logic front-loaded early starts.
    scene_cuts = [{'start_time': float(i * 5), 'duration': 5.0} for i in range(8)]
    scene_cuts.append({'start_time': 90.0, 'duration': 10.0})
    selected = _select_scene_frames_impl(frames, scene_cuts, budget=4)
    assert len(selected) == 4
    times = [float(item['pos_msec']) for item in selected]
    assert max(times) >= 50000.0  # includes a late frame near 90s scene


def test_select_scene_frames_prefers_scene_boundaries():
    frames = [
        {'pos_msec': float(i * 10000), 'frame_insight': str(i)} for i in range(10)
    ]
    scene_cuts = [
        {'start_time': 0.0, 'duration': 20.0},
        {'start_time': 50.0, 'duration': 30.0},
    ]
    selected = _select_scene_frames_impl(frames, scene_cuts, budget=4)
    assert len(selected) == 4


def test_summarize_frame_context_caps_entries():
    frames = [
        {'pos_msec': float(i * 1000), 'segment_start': 0.0, 'frame_insight': f'scene {i}'}
        for i in range(20)
    ]
    summarized = _summarize_frame_context_impl(frames, max_entries=5)
    assert len(summarized) == 5


def test_truncate_frame_context_spreads_timeline():
    frames = [
        {'pos_msec': float(i), 'segment_start': 0.0, 'frame_insight': str(i)}
        for i in range(10)
    ]
    truncated = _truncate_frame_context_impl(frames, max_frames=3)
    assert len(truncated) == 3
    assert truncated[0]['frame_insight'] == '0'
    assert truncated[-1]['frame_insight'] == '9'


def test_dedupe_frame_context_collapses_repeats():
    frames = [
        {'pos_msec': 0.0, 'segment_start': 0.0, 'frame_insight': 'Two men talking.'},
        {'pos_msec': 1000.0, 'segment_start': 0.0, 'frame_insight': 'two men talking.'},
        {'pos_msec': 2000.0, 'segment_start': 1.0, 'frame_insight': 'Elevator scene.'},
    ]
    deduped = _dedupe_frame_context_impl(frames)
    assert len(deduped) == 2


def test_scene_cut_segment_times_from_scenes():
    cuts = [
        {'start_time': 0.0, 'duration': 10.0},
        {'start_time': 10.0, 'duration': 5.0},
        {'start_time': 15.0, 'duration': 100.0},
    ]
    assert _scene_cut_segment_times_impl(cuts, 115.0) == [10.0, 15.0]


def test_scene_cut_segment_times_single_scene():
    cuts = [{'start_time': 0.0, 'duration': 255.0}]
    assert _scene_cut_segment_times_impl(cuts, 255.0) == []


def test_scene_cut_segment_times_fallback():
    assert _time_window_segment_times_impl(25.0, 10.0) == [10.0, 20.0]
    assert _scene_cut_segment_times_impl(None, 25.0, fallback_window_sec=10.0) == [10.0, 20.0]


def test_gemini_usage_tokens_from_metadata():
    response = {
        'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 50},
    }
    assert _gemini_usage_tokens_impl(response) == (100, 50)


def test_resolved_gemini_cost_prefers_actual_tokens():
    actual = _resolved_gemini_cost_impl(1000, 500, 10, 10, 1.50)
    estimated = _resolved_gemini_cost_impl(0, 0, 1000, 500, 1.50)
    assert actual == estimated
    assert actual > 0


def test_asr_cost_includes_audio_duration():
    transcripts = [{'segment_start': 0.0, 'segment_end': 255.0, 'text': 'hello world'}]
    cost = _asr_cost_from_transcripts_impl(transcripts, 255.0)
    # 255s * 32 tok/s input + output tokens for "hello world"
    expected_in = int(255 * GEMINI_AUDIO_TOKENS_PER_SEC)
    expected = _compute_cost_impl(expected_in, max(1, len('hello world') // 4), 1.50)
    assert abs(cost - expected) < 0.0001


def test_gemini_multimodal_synthesis_contents_caps_images():
    from video_benchmark.udfs import _gemini_multimodal_synthesis_contents_impl

    context = [{'pos_msec': float(i * 1000), 'frame_insight': str(i)} for i in range(5)]
    images = [{'pos_msec': float(i * 1000), 'frame': f'img{i}'} for i in range(5)]
    contents = _gemini_multimodal_synthesis_contents_impl(
        'prompt text', context, images, max_images=3
    )
    assert contents[0] == 'prompt text'
    assert contents[1:] == ['img0', 'img1', 'img2']


def test_fal_video_cost_and_text():
    from video_benchmark.udfs import (
        _fal_text_impl,
        _fal_video_cost_impl,
        _fal_video_understanding_input_impl,
        _resolve_fal_video_url_impl,
    )

    assert abs(_fal_video_cost_impl(255.0, max_duration_sec=120.0) - 0.24) < 1e-9
    assert abs(_fal_video_cost_impl(255.0, max_duration_sec=0.0) - 0.51) < 1e-9
    assert _fal_video_cost_impl(5.0) == 0.01
    assert _fal_text_impl({'output': 'hello'}) == 'hello'
    assert _fal_text_impl({'error': 'boom', 'output': ''}).startswith('[fal error]')
    assert _resolve_fal_video_url_impl('/tmp/x.mp4', 'https://cdn.example/v.mp4') == (
        'https://cdn.example/v.mp4'
    )
    req = _fal_video_understanding_input_impl('https://x', 'What happens?', True)
    assert req['video_url'] == 'https://x'
    assert req['detailed_analysis'] is True


def test_nova_text_and_cost():
    from video_benchmark.udfs import (
        _estimate_nova_video_tokens_impl,
        _nova_cost_impl,
        _nova_text_impl,
        _nova_usage_tokens_impl,
    )

    response = {
        'output': {'message': {'content': [{'text': 'Nova summary'}]}},
        'usage': {'inputTokens': 1000, 'outputTokens': 50},
    }
    assert _nova_text_impl(response) == 'Nova summary'
    assert _nova_usage_tokens_impl(response) == (1000, 50)
    assert _nova_text_impl({'error': 'AccessDenied', 'output': {}}).startswith('[nova error]')
    tokens = _estimate_nova_video_tokens_impl(255.0, 'q')
    assert tokens >= 255 * 288
    cost = _nova_cost_impl(1000, 50, 0, 0, 'amazon.nova-lite-v1:0')
    assert cost > 0
