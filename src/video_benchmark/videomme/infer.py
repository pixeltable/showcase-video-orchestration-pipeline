"""Per-question inference: Gemini Paths 1–2, Path 3 OSS, Path 5 Nova."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from video_benchmark.oss_providers import _oss_insight_llama_impl
from video_benchmark.udfs import (
    GEMINI_25_FLASH_INPUT_PER_M,
    GEMINI_25_FLASH_OUTPUT_PER_M,
    _estimate_nova_video_tokens_impl,
    _estimate_text_tokens_impl,
    _nova_cost_impl,
    _nova_invoke_safe_impl,
    _nova_text_impl,
    _nova_usage_tokens_impl,
)
from video_benchmark.videomme.prompts import orchestrated_mcq_prompt
from video_benchmark.videomme.scoring import extract_letter, is_correct, mcq_prompt


def _client():
    from google import genai

    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError('Set GOOGLE_API_KEY or GEMINI_API_KEY')
    return genai.Client(api_key=api_key)


def _usage_cost(response: Any) -> float:
    meta = getattr(response, 'usage_metadata', None)
    if meta is None:
        return 0.0
    inp = int(getattr(meta, 'prompt_token_count', 0) or 0)
    out = int(getattr(meta, 'candidates_token_count', 0) or 0)
    if inp == 0 and out == 0:
        return 0.0
    return (inp * GEMINI_25_FLASH_INPUT_PER_M + out * GEMINI_25_FLASH_OUTPUT_PER_M) / 1_000_000


def _response_text(response: Any) -> str:
    text = getattr(response, 'text', None)
    if text:
        return str(text)
    try:
        cands = response.candidates or []
        parts = cands[0].content.parts if cands else []
        return ''.join(str(getattr(p, 'text', '') or '') for p in parts)
    except Exception:
        return ''


def native_mcq_answer(
    *,
    video_path: str | Path,
    question: str,
    options: list[str],
    model: str,
    max_retries: int = 2,
) -> tuple[str, str | None, float]:
    """Path 1: full video + MCQ prompt. Returns (raw_text, letter, cost)."""
    client = _client()
    prompt = mcq_prompt(question, options)
    path = Path(video_path)
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            uploaded = client.files.upload(file=str(path))
            for _ in range(60):
                meta = client.files.get(name=uploaded.name)
                state = getattr(getattr(meta, 'state', None), 'name', None) or str(
                    getattr(meta, 'state', '')
                )
                if state in {'ACTIVE', 'FileState.ACTIVE'}:
                    break
                if state in {'FAILED', 'FileState.FAILED'}:
                    raise RuntimeError(f'Gemini file upload failed: {state}')
                time.sleep(2)
            response = client.models.generate_content(
                model=model,
                contents=[uploaded, prompt],
            )
            raw = _response_text(response)
            return raw, extract_letter(raw), _usage_cost(response)
        except Exception as exc:  # noqa: BLE001 — soft-retry API flakes
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'native_mcq_answer failed for {path}: {last_err}')


def orchestrated_mcq_answer(
    *,
    shared_context: str,
    question: str,
    options: list[str],
    model: str,
    video_duration_sec: float | None = None,
) -> tuple[str, str | None, float]:
    """Path 2: text synthesis over shared transcript+keyframes. Returns (raw, letter, cost)."""
    client = _client()
    prompt = orchestrated_mcq_prompt(
        question, options, shared_context, video_duration_sec=video_duration_sec
    )
    response = client.models.generate_content(model=model, contents=prompt)
    raw = _response_text(response)
    return raw, extract_letter(raw), _usage_cost(response)


def nova_mcq_answer(
    *,
    video_path: str | Path,
    question: str,
    options: list[str],
    model_id: str,
    s3_uri: str = '',
    input_rate_per_m: float = -1.0,
    output_rate_per_m: float = -1.0,
) -> tuple[str, str | None, float]:
    """Path 5: Nova native video MCQ. Soft-fail → empty letter, cost 0 on hard error."""
    prompt = mcq_prompt(question, options)
    path = str(Path(video_path).resolve())
    try:
        response = _nova_invoke_safe_impl(path, prompt, model_id, s3_uri or '')
        raw = _nova_text_impl(response)
        if isinstance(response, dict) and response.get('error') and not raw.strip():
            return f'ERROR: {response.get("error")}', None, 0.0
        if not (raw or '').strip():
            return '', None, 0.0
        actual_in, actual_out = _nova_usage_tokens_impl(response)
        est_in = _estimate_nova_video_tokens_impl(
            None, prompt
        )  # duration unknown here; usage preferred
        # Prefer duration-aware estimate when usage missing
        try:
            import av

            with av.open(path) as container:
                dur = float(container.duration or 0) / av.time_base if container.duration else 0.0
        except Exception:  # noqa: BLE001
            dur = 0.0
        if dur > 0:
            est_in = _estimate_nova_video_tokens_impl(dur, prompt)
        est_out = _estimate_text_tokens_impl(raw)
        in_override = None if float(input_rate_per_m) < 0 else float(input_rate_per_m)
        out_override = None if float(output_rate_per_m) < 0 else float(output_rate_per_m)
        cost = _nova_cost_impl(
            actual_in,
            actual_out,
            est_in,
            est_out,
            model_id,
            in_override,
            out_override,
        )
        return raw, extract_letter(raw), float(cost)
    except Exception as exc:  # noqa: BLE001
        return f'ERROR: {exc}', None, 0.0


def oss_mcq_answer(
    *,
    shared_context: str,
    question: str,
    options: list[str],
    synth_repo_id: str,
    synth_repo_filename: str,
    synth_max_tokens: int = 2048,
    video_duration_sec: float | None = None,
) -> tuple[str, str | None, float]:
    """Path 3: local 7B text synth over OSS frames + shared Gemini ASR. API cost $0."""
    prompt = orchestrated_mcq_prompt(
        question, options, shared_context, video_duration_sec=video_duration_sec
    )
    try:
        raw = _oss_insight_llama_impl(
            prompt, synth_repo_id, synth_repo_filename, synth_max_tokens
        )
        return raw or '', extract_letter(raw), 0.0
    except Exception as exc:  # noqa: BLE001
        return f'ERROR: {exc}', None, 0.0


def score_prediction(
    *,
    question_row: dict[str, Any],
    native_raw: str,
    native_letter: str | None,
    native_cost: float,
    orch_raw: str,
    orch_letter: str | None,
    orch_synth_cost: float,
    oss_raw: str | None = None,
    oss_letter: str | None = None,
    oss_synth_cost: float = 0.0,
    nova_raw: str | None = None,
    nova_letter: str | None = None,
    nova_cost: float = 0.0,
    run_native: bool = True,
    run_orch: bool = True,
) -> dict[str, Any]:
    gold = str(question_row.get('answer') or '').upper()[:1]
    native_failed = run_native and (
        not (native_raw or '').strip() or str(native_raw).startswith('ERROR:')
    )
    nova_failed = nova_raw is not None and (
        not (nova_raw or '').strip()
        or str(nova_raw).startswith('ERROR:')
        or '[nova error]' in str(nova_raw).lower()
        or 'validationexception' in str(nova_raw).lower()
    )
    return {
        'question_id': question_row['question_id'],
        'video_id': question_row['video_id'],
        'duration': question_row.get('duration'),
        'domain': question_row.get('domain'),
        'task_type': question_row.get('task_type'),
        'gold': gold,
        'native_raw': native_raw if run_native else None,
        'native_letter': native_letter if run_native else None,
        'native_correct': is_correct(native_letter, gold) if run_native else None,
        'native_cost': float(native_cost) if run_native else 0.0,
        'native_ingest_failed': bool(native_failed and native_letter is None),
        'orchestrated_raw': orch_raw if run_orch else None,
        'orchestrated_letter': orch_letter if run_orch else None,
        'orchestrated_correct': is_correct(orch_letter, gold) if run_orch else None,
        'orchestrated_synth_cost': float(orch_synth_cost) if run_orch else 0.0,
        'oss_raw': oss_raw,
        'oss_letter': oss_letter,
        'oss_correct': is_correct(oss_letter, gold) if oss_raw is not None else None,
        'oss_synth_cost': float(oss_synth_cost),
        'nova_raw': nova_raw,
        'nova_letter': nova_letter,
        'nova_correct': is_correct(nova_letter, gold) if nova_raw is not None else None,
        'nova_cost': float(nova_cost),
        'nova_ingest_failed': bool(nova_failed and nova_letter is None),
    }
