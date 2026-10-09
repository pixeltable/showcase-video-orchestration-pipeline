"""Test session setup: an isolated Pixeltable home and an offline Gemini stand-in."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from video_benchmark.local_demo import make_demo_video as make_test_video

# Before any test touches the catalog: never write to the developer's ~/.pixeltable.
TEST_HOME = Path(tempfile.mkdtemp(prefix='pxt-tests-'))
os.environ['PIXELTABLE_HOME'] = str(TEST_HOME)
# No test may reach a paid provider: replace real keys from the shell with dummies.
os.environ['GOOGLE_API_KEY'] = 'test-key'
for _key in (
    'GEMINI_API_KEY',
    'FAL_KEY',
    'FAL_API_KEY',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_BEARER_TOKEN_BEDROCK',
    'BEDROCK_API_KEY',
):
    os.environ.pop(_key, None)


@pytest.fixture(scope='session', autouse=True)
def throwaway_catalog():
    """Pixeltable leaves its Postgres running after exit; stop it and delete the test home."""
    yield
    from pixeltable_pgserver import pg_ctl

    if (TEST_HOME / 'pgdata').exists():
        try:
            pg_ctl(['-m', 'fast', '-w', 'stop'], pgdata=TEST_HOME / 'pgdata')
        except subprocess.CalledProcessError:
            pass  # already stopped
    shutil.rmtree(TEST_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Keep the project .env (real keys) out of every test."""
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)


@dataclass
class FakeResponse:
    payload: dict

    def model_dump(self) -> dict:
        return self.payload


@dataclass
class FakeGemini:
    """Stands in for `genai.Client`: answers by prompt kind and records every call."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    # Kinds of call that raise, to exercise failure handling.
    fail_kinds: set[str] = field(default_factory=set)
    # Kinds of call that return no text, as a recitation or safety stop does.
    empty_kinds: set[str] = field(default_factory=set)
    missing_usage_kinds: set[str] = field(default_factory=set)
    missing_usage_calls: dict[str, set[int]] = field(default_factory=dict)
    blocked_kinds: set[str] = field(default_factory=set)
    ambiguous_cache_kinds: set[str] = field(default_factory=set)

    @property
    def aio(self) -> FakeGemini:
        return self

    @property
    def models(self) -> FakeGemini:
        return self

    async def generate_content(
        self, *, model: str, contents: Any, config: Any = None
    ) -> FakeResponse:
        items = contents if isinstance(contents, list) else [contents]
        text = ' '.join(str(item) for item in items if isinstance(item, str))
        if text.startswith('Transcribe this audio'):
            kind, answer = 'asr', '[00:00] Speaker 1: Hello there.\n[00:02] Speaker 2: Nice pants.'
        elif 'evidence below' in text:
            kind, answer = 'synthesis', 'Orchestrated answer: two speakers talk.'
        elif 'This keyframe is at' in text:
            # Echo the timestamp so captions differ per frame (identical ones are deduped).
            seconds = text.split('This keyframe is at ', 1)[1].split('s', 1)[0]
            kind, answer = 'caption', f'A plain frame, {seconds} seconds in.'
        else:
            kind, answer = 'native', 'Native answer: two speakers talk.'
        if 'Choose exactly one of A, B, C' in text:
            answer += '\nAnswer: B'
        self.calls.append(
            {'kind': kind, 'model': model, 'contents': items, 'config': config, 'text': text}
        )
        if kind in self.fail_kinds:
            raise RuntimeError(f'injected {kind} failure')
        # Token counts are arbitrary but distinct per kind, so costs can be checked exactly.
        modality = {'native': 'VIDEO', 'caption': 'IMAGE', 'asr': 'AUDIO'}.get(kind, 'TEXT')
        prompt_tokens = {'native': 1000, 'caption': 300, 'asr': 500, 'synthesis': 2000}[kind]
        if kind in self.empty_kinds:
            candidate = {'finish_reason': 'RECITATION', 'content': None}
        else:
            candidate = {'finish_reason': 'STOP', 'content': {'parts': [{'text': answer}]}}
        payload = {
                'candidates': [candidate],
                'usage_metadata': {
                    'prompt_token_count': prompt_tokens,
                    'prompt_tokens_details': [
                        {'modality': modality, 'token_count': prompt_tokens - 10},
                        {'modality': 'TEXT', 'token_count': 10},
                    ],
                    'candidates_token_count': 100,
                    'thoughts_token_count': 50 if kind in {'native', 'synthesis'} else 0,
                },
            }
        call_number = sum(call['kind'] == kind for call in self.calls)
        if (kind in self.missing_usage_kinds
                or call_number in self.missing_usage_calls.get(kind, set())):
            payload.pop('usage_metadata')
        if kind in self.blocked_kinds:
            payload['candidates'] = None
            payload['prompt_feedback'] = {'block_reason': 'PROHIBITED_CONTENT'}
        if kind in self.ambiguous_cache_kinds:
            payload['usage_metadata']['prompt_tokens_details'] = [
                {'modality': 'VIDEO', 'token_count': prompt_tokens // 2},
                {'modality': 'AUDIO', 'token_count': prompt_tokens // 2},
            ]
            payload['usage_metadata']['cached_content_token_count'] = prompt_tokens // 2
        return FakeResponse(payload)


@pytest.fixture
def fake_gemini(monkeypatch) -> FakeGemini:
    import pixeltable.functions.gemini as pxt_gemini

    from video_benchmark import providers

    fake = FakeGemini()
    monkeypatch.setattr(pxt_gemini, '_genai_client', lambda: fake)
    monkeypatch.setattr(providers, '_gemini_client', lambda: fake)
    return fake


@pytest.fixture(scope='session')
def test_video(tmp_path_factory) -> Path:
    return make_test_video(tmp_path_factory.mktemp('media') / 'tiny.mp4')
