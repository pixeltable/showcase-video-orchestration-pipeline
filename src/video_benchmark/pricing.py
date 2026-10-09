"""Provider prices, and the cost of one call computed from the usage its response reports.

Costs come only from reported token counts, never from text-length estimates. Every call's
usage is stored next to its cost, so a run can be re-priced when a rate changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pixeltable as pxt

PRICES_AS_OF = '2026-09-28'
PRICE_SOURCES = {
    'gemini': 'https://ai.google.dev/gemini-api/docs/pricing (paid tier, standard, not batch)',
    'nova': 'AWS Price List API, service AmazonBedrock, us-east-1, on-demand standard',
    'fal': 'https://fal.ai/models/fal-ai/video-understanding',
}


@dataclass(frozen=True)
class GeminiRates:
    """USD per 1M tokens. Input rates are keyed by the modality the API reports."""

    input: dict[str, float]
    cached_input: dict[str, float]
    output: float  # candidates and thinking tokens are billed alike


GEMINI_RATES = {
    'gemini-2.5-flash': GeminiRates(
        input={'TEXT': 0.30, 'IMAGE': 0.30, 'VIDEO': 0.30, 'AUDIO': 1.00},
        cached_input={'TEXT': 0.03, 'IMAGE': 0.03, 'VIDEO': 0.03, 'AUDIO': 0.10},
        output=2.50,
    ),
    'gemini-2.5-flash-lite': GeminiRates(
        input={'TEXT': 0.10, 'IMAGE': 0.10, 'VIDEO': 0.10, 'AUDIO': 0.30},
        cached_input={'TEXT': 0.01, 'IMAGE': 0.01, 'VIDEO': 0.01, 'AUDIO': 0.03},
        output=0.40,
    ),
}

# USD per 1M tokens: (input, output). Bedrock bills video input at the input-token rate.
NOVA_RATES = {
    'amazon.nova-micro-v1:0': (0.035, 0.14),
    'amazon.nova-lite-v1:0': (0.06, 0.24),
    'amazon.nova-pro-v1:0': (0.80, 3.20),
    'amazon.nova-premier-v1:0': (2.50, 12.50),
}

FAL_USD_PER_5_SEC = 0.01


def _field(obj: Any, snake: str, camel: str) -> Any:
    if not isinstance(obj, dict):
        return None
    value = obj.get(snake)
    return obj.get(camel) if value is None else value


def _modality_name(value: Any) -> str:
    # In memory the SDK yields MediaModality enums; stored JSON holds their string values.
    name = str(getattr(value, 'value', value) or 'TEXT')
    return name.rsplit('.', 1)[-1].upper()


def _modality_counts(details: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in details or []:
        modality = _modality_name(_field(item, 'modality', 'modality'))
        tokens = int(_field(item, 'token_count', 'tokenCount') or 0)
        counts[modality] = counts.get(modality, 0) + tokens
    return counts


def gemini_usage_impl(response: dict) -> dict:
    """Token counts from a generate_content response (`response.model_dump()`)."""
    meta = _field(response, 'usage_metadata', 'usageMetadata') or {}
    if _field(meta, 'prompt_token_count', 'promptTokenCount') is None:
        raise ValueError('Gemini returned no input-token usage; cost is unknown, not zero')
    return {
        'input_tokens': int(_field(meta, 'prompt_token_count', 'promptTokenCount') or 0),
        'input_by_modality': _modality_counts(
            _field(meta, 'prompt_tokens_details', 'promptTokensDetails')
        ),
        'cached_tokens': int(
            _field(meta, 'cached_content_token_count', 'cachedContentTokenCount') or 0
        ),
        'cached_by_modality': _modality_counts(
            _field(meta, 'cache_tokens_details', 'cacheTokensDetails')
        ),
        'output_tokens': int(_field(meta, 'candidates_token_count', 'candidatesTokenCount') or 0),
        'thinking_tokens': int(_field(meta, 'thoughts_token_count', 'thoughtsTokenCount') or 0),
    }


def _rate(rates: dict[str, float], modality: str) -> float:
    # DOCUMENT and unspecified modalities bill as text.
    return rates.get(modality, rates['TEXT'])


def gemini_cost_parts_impl(usage: dict, model: str) -> dict[str, float]:
    """USD of one call by billed part: 'input_<MODALITY>', 'cached_input', 'output', 'thinking'.

    Cached prompt tokens bill at the cache rate, the rest at the input rate of their modality;
    prompt tokens the API reports without a modality bill as text.
    """
    rates = GEMINI_RATES[model]
    fresh = dict(usage.get('input_by_modality') or {})
    cached = dict(usage.get('cached_by_modality') or {})
    input_tokens = int(usage.get('input_tokens') or 0)
    unattributed = input_tokens - sum(fresh.values())
    if unattributed > 0:
        fresh['TEXT'] = fresh.get('TEXT', 0) + unattributed
    if not cached and usage.get('cached_tokens'):
        # When all input modalities have the same price pair, cache allocation does not
        # affect the total. Mixed audio/video without allocation has no exact price.
        rate_pairs = {
            (_rate(rates.input, m), _rate(rates.cached_input, m))
            for m, n in fresh.items() if n > 0
        }
        if len(rate_pairs) != 1:
            raise ValueError('Cached-token modality breakdown is missing; cost is unknown')
        remaining = int(usage['cached_tokens'])
        for modality, tokens in fresh.items():
            cached[modality] = min(tokens, remaining)
            remaining -= cached[modality]
        if remaining:
            raise ValueError('Cached-token count exceeds reported input tokens')
    for modality, tokens in cached.items():
        fresh[modality] = fresh.get(modality, 0) - tokens
    parts = {f'input_{m}': max(0, n) * _rate(rates.input, m) / 1e6 for m, n in fresh.items()}
    parts['cached_input'] = sum(n * _rate(rates.cached_input, m) for m, n in cached.items()) / 1e6
    parts['output'] = int(usage.get('output_tokens') or 0) * rates.output / 1e6
    parts['thinking'] = int(usage.get('thinking_tokens') or 0) * rates.output / 1e6
    return parts


def gemini_cost_impl(usage: dict, model: str) -> float:
    """USD for one call: the sum of its billed parts."""
    return sum(gemini_cost_parts_impl(usage, model).values())


def uncached_usage_impl(usage: dict) -> dict:
    """The same call priced as if nothing had been cached (list price).

    Gemini's implicit cache discounts repeated prompt prefixes at its own discretion, so billed
    cost varies between identical runs; comparisons between paths use list price.
    """
    return {**usage, 'cached_tokens': 0, 'cached_by_modality': {}}


def _nova_base_model(model_id: str) -> str:
    # Cross-region inference profiles prefix the model id, e.g. 'us.amazon.nova-pro-v1:0'.
    parts = model_id.split('.', 1)
    return parts[1] if len(parts) == 2 and parts[0] in {'us', 'eu', 'apac', 'global'} else model_id


def nova_usage_impl(response: dict) -> dict:
    usage = response.get('usage') or {}
    if usage.get('inputTokens') is None or usage.get('outputTokens') is None:
        raise ValueError('Bedrock returned no token usage; cost is unknown, not zero')
    return {
        'input_tokens': int(usage.get('inputTokens') or 0),
        'output_tokens': int(usage.get('outputTokens') or 0),
    }


def nova_cost_impl(usage: dict, model_id: str) -> float:
    rate_in, rate_out = nova_model_rates(model_id)
    return (usage['input_tokens'] * rate_in + usage['output_tokens'] * rate_out) / 1_000_000


def nova_model_rates(model_id: str) -> tuple[float, float]:
    try:
        return NOVA_RATES[_nova_base_model(model_id)]
    except KeyError:
        raise ValueError(f'NOVA_MODEL_ID={model_id!r} has no price in pricing.NOVA_RATES') from None


def fal_cost_impl(duration_sec: float, max_duration_sec: float) -> float:
    """fal bills $0.01 per started 5 s of the (trimmed) input clip."""
    billed = min(max(0.0, duration_sec), max_duration_sec)
    return math.ceil(billed / 5.0) * FAL_USD_PER_5_SEC if billed > 0 else 0.0


@pxt.udf
def gemini_usage(response: dict) -> dict:
    return gemini_usage_impl(response)


@pxt.udf
def gemini_cost(usage: dict, model: str) -> float:
    return gemini_cost_impl(usage, model)


@pxt.udf
def nova_usage(response: dict) -> dict:
    return nova_usage_impl(response)


@pxt.udf
def nova_cost(usage: dict, model_id: str) -> float:
    return nova_cost_impl(usage, model_id)


@pxt.udf
def fal_cost(duration_sec: float, max_duration_sec: float) -> float:
    return fal_cost_impl(duration_sec, max_duration_sec)


def sum_costs_impl(rows: list) -> float:
    """Sum known usage-priced costs. Missing usage and retries may incur unrecorded spend."""
    return float(sum(row['cost'] for row in rows if isinstance(row, dict) and row.get('cost')))


@pxt.udf
def sum_costs(rows: list) -> float:
    return sum_costs_impl(rows)
