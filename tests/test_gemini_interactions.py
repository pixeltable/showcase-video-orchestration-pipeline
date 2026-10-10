"""Check the real SDK protocol without creating provider interactions."""

import asyncio
import json

import httpx
import pytest
from google import genai

from video_benchmark import admission


@pytest.mark.parametrize('mode', ['static', 'agentic'])
def test_sdk_preserves_video_processing_mode(monkeypatch, mode):
    captured = []

    class RequestCaptured(Exception):
        pass

    def capture(client, request, *args, **kwargs):
        captured.append(json.loads(request.content))
        raise RequestCaptured

    monkeypatch.setattr(httpx.Client, 'send', capture)
    with genai.Client(api_key='offline-test-key') as client:
        with pytest.raises(RequestCaptured):
            client.interactions.create(
                model='gemini-3.8-flash',
                input=[
                    {'type': 'video', 'uri': 'https://example.org/fixture.mp4',
                     'mime_type': 'video/mp4', 'processing': mode},
                    {'type': 'text', 'text': 'Describe the fixture.'},
                ],
            )
    # Older SDKs silently stripped this field, falsely labelling static calls agentic.
    assert len(captured) == 1
    assert captured[0]['input'][0]['content'][0]['processing'] == mode


@pytest.mark.parametrize('transport', ['async', 'sync'])
def test_real_interactions_sdk_is_rejected_before_transport(tmp_path, monkeypatch, transport):
    def unexpected_send(*args, **kwargs):
        raise AssertionError('An unreserved model request reached the transport')

    async def unexpected_async_send(*args, **kwargs):
        unexpected_send()

    monkeypatch.setattr(httpx.Client, 'send', unexpected_send)
    monkeypatch.setattr(httpx.AsyncClient, 'send', unexpected_async_send)
    journal = admission.AttemptLedger(tmp_path / 'attempts.sqlite3', budget_usd=1)

    async def run():
        with admission.provider_session(journal, seconds=4):
            client = genai.Client(api_key='offline-test-key')
            try:
                with pytest.raises(admission.AdmissionError):
                    if transport == 'async':
                        await client.aio.interactions.create(
                            model='gemini-3.8-flash', input='Describe the fixture.'
                        )
                    else:
                        client.interactions.create(
                            model='gemini-3.8-flash', input='Describe the fixture.'
                        )
            finally:
                await client.aio.aclose()
                client.close()

    asyncio.run(run())
    assert journal.snapshot()['attempts'] == []
