"""Cost from reported usage: per-modality input rates, thinking billed as output, caching."""

from __future__ import annotations

import pytest
from google.genai import types

from video_benchmark.pricing import (
    fal_cost_impl,
    gemini_cost_impl,
    gemini_usage_impl,
    nova_cost_impl,
    nova_usage_impl,
    sum_costs_impl,
)


def _response(**usage) -> dict:
    return {'candidates': [], 'usage_metadata': usage}


def test_usage_reads_modalities_from_sdk_dump():
    # response.model_dump() keeps MediaModality enums; stored JSON holds plain strings.
    meta = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=74_000,
        prompt_tokens_details=[
            types.ModalityTokenCount(modality='VIDEO', token_count=65_800),
            types.ModalityTokenCount(modality='AUDIO', token_count=8_150),
            types.ModalityTokenCount(modality='TEXT', token_count=50),
        ],
        candidates_token_count=700,
        thoughts_token_count=1_200,
    ).model_dump()
    usage = gemini_usage_impl({'usage_metadata': meta})
    assert usage['input_by_modality'] == {'VIDEO': 65_800, 'AUDIO': 8_150, 'TEXT': 50}
    assert (usage['output_tokens'], usage['thinking_tokens']) == (700, 1_200)


def test_usage_accepts_camel_case():
    usage = gemini_usage_impl(
        {
            'usageMetadata': {
                'promptTokenCount': 10,
                'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 10}],
                'candidatesTokenCount': 5,
            }
        }
    )
    assert usage['input_tokens'] == 10 and usage['output_tokens'] == 5


def test_native_video_cost_bills_audio_track_and_thinking():
    usage = gemini_usage_impl(
        _response(
            prompt_token_count=74_000,
            prompt_tokens_details=[
                {'modality': 'VIDEO', 'token_count': 65_800},
                {'modality': 'AUDIO', 'token_count': 8_150},
                {'modality': 'TEXT', 'token_count': 50},
            ],
            candidates_token_count=700,
            thoughts_token_count=1_200,
        )
    )
    expected = (65_850 * 0.30 + 8_150 * 1.00 + 1_900 * 2.50) / 1e6
    assert gemini_cost_impl(usage, 'gemini-2.5-flash') == pytest.approx(expected)


def test_cached_tokens_bill_at_cache_rate():
    usage = gemini_usage_impl(
        _response(
            prompt_token_count=10_000,
            prompt_tokens_details=[{'modality': 'VIDEO', 'token_count': 10_000}],
            cached_content_token_count=8_000,
            cache_tokens_details=[{'modality': 'VIDEO', 'token_count': 8_000}],
            candidates_token_count=100,
        )
    )
    expected = (2_000 * 0.30 + 8_000 * 0.03 + 100 * 2.50) / 1e6
    assert gemini_cost_impl(usage, 'gemini-2.5-flash') == pytest.approx(expected)


def test_cache_without_modality_details_is_exact_when_input_rates_are_equal():
    usage = gemini_usage_impl(_response(
        prompt_token_count=1000,
        prompt_tokens_details=[{'modality': 'VIDEO', 'token_count': 1000}],
        cached_content_token_count=500,
    ))
    assert gemini_cost_impl(usage, 'gemini-2.5-flash') == pytest.approx(0.000165)
    usage['input_by_modality'] = {'VIDEO': 500, 'AUDIO': 500}
    with pytest.raises(ValueError, match='breakdown is missing'):
        gemini_cost_impl(usage, 'gemini-2.5-flash')


def test_missing_usage_does_not_make_a_model_call_appear_free():
    with pytest.raises(ValueError, match='cost is unknown'):
        gemini_usage_impl({'candidates': []})
    with pytest.raises(ValueError, match='cost is unknown'):
        nova_usage_impl({'output': {'message': {'content': []}}})


def test_unattributed_prompt_tokens_bill_as_text():
    usage = gemini_usage_impl(_response(prompt_token_count=1_000, candidates_token_count=0))
    assert gemini_cost_impl(usage, 'gemini-2.5-flash') == pytest.approx(1_000 * 0.30 / 1e6)


def test_nova_cost_strips_inference_profile_prefix():
    usage = nova_usage_impl({'usage': {'inputTokens': 70_000, 'outputTokens': 500}})
    expected = (70_000 * 0.80 + 500 * 3.20) / 1e6
    assert nova_cost_impl(usage, 'us.amazon.nova-pro-v1:0') == pytest.approx(expected)
    assert nova_cost_impl(usage, 'amazon.nova-premier-v1:0') == pytest.approx(
        (70_000 * 2.50 + 500 * 12.50) / 1e6
    )


def test_fal_bills_started_five_second_blocks_of_the_trimmed_clip():
    assert fal_cost_impl(254.96, 120.0) == pytest.approx(0.24)
    assert fal_cost_impl(7.0, 120.0) == pytest.approx(0.02)
    assert fal_cost_impl(0.0, 120.0) == 0.0


def test_sum_costs_keeps_unknown_paid_attempts_unknown():
    assert sum_costs_impl([{'cost': 0.25}, {'cost': None}, {'cost': 0.5}]) is None
    assert sum_costs_impl([{'cost': 0.25}, {'cost': 0.0}, {'cost': 0.5}]) == pytest.approx(0.75)
    assert sum_costs_impl([]) == 0.0


def test_list_price_removes_the_cache_discount_and_parts_sum_to_cost():
    from video_benchmark.pricing import gemini_cost_parts_impl, uncached_usage_impl

    usage = gemini_usage_impl(
        _response(
            prompt_token_count=75_284,
            prompt_tokens_details=[
                {'modality': 'VIDEO', 'token_count': 67_065},
                {'modality': 'AUDIO', 'token_count': 8_160},
                {'modality': 'TEXT', 'token_count': 59},
            ],
            cached_content_token_count=75_100,
            cache_tokens_details=[
                {'modality': 'VIDEO', 'token_count': 66_902},
                {'modality': 'AUDIO', 'token_count': 8_140},
                {'modality': 'TEXT', 'token_count': 58},
            ],
            candidates_token_count=1_793,
            thoughts_token_count=1_057,
        )
    )
    billed = gemini_cost_impl(usage, 'gemini-2.5-flash')
    listed = gemini_cost_impl(uncached_usage_impl(usage), 'gemini-2.5-flash')
    # The Pursuit run whose native call was served from Gemini's implicit cache.
    assert billed == pytest.approx(0.0100, abs=5e-5)
    assert listed == pytest.approx((67_124 * 0.30 + 8_160 * 1.00 + 2_850 * 2.50) / 1e6)
    parts = gemini_cost_parts_impl(usage, 'gemini-2.5-flash')
    assert sum(parts.values()) == pytest.approx(billed)
    assert parts['thinking'] == pytest.approx(1_057 * 2.50 / 1e6)
