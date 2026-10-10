"""Real SDK transports with offline responses; no paid or external HTTP requests."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from video_benchmark import admission

URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
PAYLOAD = {
    'contents': [{'parts': [{'text': 'Describe the fixture.'}]}],
    'generationConfig': {'maxOutputTokens': 4096},
}
RESPONSE = {
    'candidates': [{'content': {'parts': [{'text': 'A tone.'}]}}],
    'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 10},
}


def ledger(tmp_path, *, budget=1, attempts=64):
    return admission.AttemptLedger(
        tmp_path / 'attempts.sqlite3', budget_usd=budget, max_attempts=attempts
    )


def test_concurrent_reservations_cannot_overspend_and_survive_reopen(tmp_path):
    journal = ledger(tmp_path)

    def reserve(_):
        try:
            return journal.reserve('gemini', 'gemini-2.5-flash', 0.6)
        except admission.AdmissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(reserve, range(2)))
    assert sum(bool(value) for value in attempts) == 1
    resumed = ledger(tmp_path)
    assert resumed.snapshot()['held_unknown_reservation_usd'] == 0.6
    with pytest.raises(admission.AdmissionError):
        resumed.reserve('gemini', 'gemini-2.5-flash', 0.5)
    assert Path(journal.path).stat().st_mode & 0o777 == 0o600


def test_usage_receipt_cannot_be_erased_by_later_cell_error(tmp_path):
    journal = ledger(tmp_path)
    attempt = journal.reserve('gemini', 'gemini-2.5-flash', 0.1)
    journal.finish(attempt, response=RESPONSE, cost_usd=0.001)
    journal.finish(attempt, error_class='TypeError')
    assert journal.snapshot()['known_response_accounted_cost_usd'] == 0.001
    assert journal.snapshot()['unknown_or_pending_attempts'] == 0


def test_actual_google_sdk_uses_guarded_transport(tmp_path, monkeypatch):
    from google import genai

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=RESPONSE)

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    journal = ledger(tmp_path)

    async def run():
        with admission.provider_session(journal, seconds=4):
            client = genai.Client(api_key='test-key')
            try:
                response = await client.aio.models.generate_content(
                    model='gemini-2.5-flash',
                    contents='Describe the fixture.',
                    config={'max_output_tokens': 4096},
                )
                assert response.text == 'A tone.'
            finally:
                await client.aio.aclose()
                client.close()

    asyncio.run(run())
    assert len(calls) == 1
    snapshot = journal.snapshot()
    assert len(snapshot['attempts']) == 1 and snapshot['unknown_or_pending_attempts'] == 0
    assert snapshot['known_response_accounted_cost_usd'] > 0
    assert 'test-key' not in json.dumps(snapshot)


def test_unknown_usage_and_retry_hold_charge_risk_and_stop_next_send(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200, json={'candidates': None, 'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'}}
        )

    journal = ledger(tmp_path, attempts=2)

    async def run():
        with admission.provider_session(journal, seconds=4):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                for _ in range(2):
                    await client.post(URL, json=PAYLOAD)
                with pytest.raises(admission.AdmissionError):
                    await client.post(URL, json=PAYLOAD)

    asyncio.run(run())
    snapshot = journal.snapshot()
    assert len(calls) == 2 and snapshot['unknown_or_pending_attempts'] == 2
    assert snapshot['held_unknown_reservation_usd'] > 0
    assert all('PROHIBITED_CONTENT' in row['response_json'] for row in snapshot['attempts'])


def test_timeout_remains_unknown_and_exhausted_budget_blocks_before_send(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('Do not record raw errors or secret URLs.')

    journal = ledger(tmp_path, budget=0.015)

    async def run():
        with admission.provider_session(journal, seconds=4):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                with pytest.raises(httpx.ReadTimeout):
                    await client.post(URL, json=PAYLOAD)
                with pytest.raises(admission.AdmissionError):
                    await client.post(URL, json=PAYLOAD)

    asyncio.run(run())
    assert len(calls) == 1
    attempt = journal.snapshot()['attempts'][0]
    assert attempt['state'] == 'unknown' and attempt['cost_usd'] is None
    assert attempt['error_class'] == 'ReadTimeout'


def test_downloads_not_counted_and_unknown_paid_destinations_fail_closed(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={})

    journal = ledger(tmp_path)

    async def run():
        with admission.provider_session(journal, seconds=4):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                await client.get('https://example.org/video.mp4')
                with pytest.raises(admission.AdmissionError):
                    await client.post('https://queue.fal.run/unknown/model', json={})
                with pytest.raises(admission.AdmissionError):
                    await client.post(URL, json={'contents': []})

    asyncio.run(run())
    assert len(calls) == 1 and journal.snapshot()['attempts'] == []


def test_actual_fal_sdk_queue_submission_counted_once_polling_is_not(tmp_path, monkeypatch):
    import fal_client

    calls = []

    def handle(request):
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(
                200,
                json={
                    'request_id': 'offline-request',
                    'response_url': 'https://queue.fal.run/fal-ai/video-understanding/requests/offline-request',
                    'status_url': 'https://queue.fal.run/fal-ai/video-understanding/requests/offline-request/status',
                    'cancel_url': 'https://queue.fal.run/fal-ai/video-understanding/requests/offline-request/cancel',
                },
            )
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'status': 'COMPLETED', 'logs': []})
        return httpx.Response(200, json={'output': 'A tone.'})

    original_init = httpx.AsyncClient.__init__

    def init(client, *args, **kwargs):
        kwargs['transport'] = httpx.MockTransport(handle)
        original_init(client, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, '__init__', init)
    journal = ledger(tmp_path)

    async def run():
        with admission.provider_session(journal, seconds=4):
            client = fal_client.AsyncClient(key='test-key')
            result = await client.subscribe(
                'fal-ai/video-understanding',
                arguments={
                    'video_url': 'https://example.org/fixture.mp4',
                    'prompt': 'Describe the fixture',
                },
            )
            assert result['output'] == 'A tone.'

    asyncio.run(run())
    assert len([call for call in calls if call.method == 'POST']) == 1
    assert len(journal.snapshot()['attempts']) == 1
    assert journal.snapshot()['known_response_accounted_cost_usd'] == 0.01


def test_actual_boto3_transport_events_reserve_before_send(tmp_path, monkeypatch):
    import boto3
    from botocore.awsrequest import AWSResponse
    from botocore.httpsession import URLLib3Session

    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'offline-access')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'offline-secret')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    payload = {
        'output': {'message': {'role': 'assistant', 'content': [{'text': 'A bright cut.'}]}},
        'usage': {'inputTokens': 100, 'outputTokens': 10},
        'stopReason': 'end_turn',
        'metrics': {'latencyMs': 1},
    }
    journal = ledger(tmp_path)
    calls = []

    class Raw:
        def stream(self, amt=None, decode_content=False):
            yield json.dumps(payload).encode()

    def send(client, request):
        calls.append(request)
        assert journal.snapshot()['attempts'][0]['state'] == 'pending'
        return AWSResponse(request.url, 200, {}, Raw())

    monkeypatch.setattr(URLLib3Session, 'send', send)
    with admission.provider_session(journal, seconds=4, bedrock_enabled=True):
        client = boto3.client('bedrock-runtime')
        assert client.meta.config.retries['total_max_attempts'] == 1
        result = client.converse(
            modelId='amazon.nova-pro-v1:0',
            messages=[{'role': 'user', 'content': [{'text': 'Describe'}]}],
            inferenceConfig={'maxTokens': 4096},
        )
        assert result['usage']['inputTokens'] == 100
    assert len(calls) == 1 and len(journal.snapshot()['attempts']) == 1
    assert journal.snapshot()['known_response_accounted_cost_usd'] > 0


@pytest.mark.parametrize('operation', ['invoke', 'converse-stream'])
def test_unsupported_bedrock_operations_fail_before_send(tmp_path, monkeypatch, operation):
    from botocore.awsrequest import AWSRequest
    from botocore.httpsession import URLLib3Session

    def unexpected_send(client, request):
        raise AssertionError('Unsupported model operation reached the transport')

    monkeypatch.setattr(URLLib3Session, 'send', unexpected_send)
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    journal = ledger(tmp_path)
    request = AWSRequest(
        method='POST',
        url=f'https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-pro-v1:0/{operation}',
        data='{}',
    ).prepare()
    with admission.provider_session(journal, seconds=4, bedrock_enabled=True):
        with pytest.raises(admission.AdmissionError):
            URLLib3Session().send(request)
    assert journal.snapshot()['attempts'] == []


def test_warmed_bedrock_client_and_bearer_auth_cannot_bypass(tmp_path, monkeypatch):
    import boto3
    from botocore.awsrequest import AWSResponse
    from botocore.config import Config
    from botocore.httpsession import URLLib3Session

    calls = []

    class Raw:
        def stream(self, amt=None, decode_content=False):
            yield json.dumps({'usage': {'inputTokens': 100, 'outputTokens': 10}}).encode()

    def send(client, request):
        calls.append(request)
        return AWSResponse(request.url, 200, {}, Raw())

    monkeypatch.setattr(URLLib3Session, 'send', send)
    # Construct before the managed session and mimic the SDK's config-derived bearer client.
    client = boto3.Session(
        aws_access_key_id='bedrock-api-key',
        aws_secret_access_key='bedrock-api-key',
        region_name='us-east-1',
    ).client('bedrock-runtime', config=Config(retries={'total_max_attempts': 1}))

    def bearer(request, **kwargs):
        request.headers['Authorization'] = 'Bearer offline-private-token'

    client.meta.events.register('before-send', bearer)
    journal = ledger(tmp_path, attempts=1)
    kwargs = {
        'modelId': 'amazon.nova-pro-v1:0',
        'messages': [{'role': 'user', 'content': [{'text': 'Describe'}]}],
        'inferenceConfig': {'maxTokens': 4096},
    }
    with admission.provider_session(journal, seconds=4, bedrock_enabled=True):
        client.converse(**kwargs)
        with pytest.raises(admission.AdmissionError):
            client.converse(**kwargs)
    assert len(calls) == 1 and 'offline-private-token' not in json.dumps(journal.snapshot())
    # The same warmed client is guarded against a new ledger, not left attached to the old one.
    second = admission.AttemptLedger(tmp_path / 'second.sqlite3', budget_usd=1)
    with admission.provider_session(second, seconds=4, bedrock_enabled=True):
        client.converse(**kwargs)
    assert len(second.snapshot()['attempts']) == 1


def test_vertex_and_custom_model_endpoints_fail_before_send(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=RESPONSE)

    async def run():
        with admission.provider_session(ledger(tmp_path), seconds=4):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                for url in (
                    'https://us-central1-aiplatform.googleapis.com/v1/projects/example/locations/'
                    'us-central1/publishers/google/models/gemini-2.5-flash:generateContent',
                    'https://custom.example/v1/models/gemini-2.5-flash:generateContent',
                ):
                    with pytest.raises(admission.AdmissionError):
                        await client.post(url, json=PAYLOAD)

    asyncio.run(run())
    assert calls == []


@pytest.mark.parametrize('transport', ['async', 'sync', 'aiohttp'])
def test_interactions_cannot_bypass_admission(tmp_path, monkeypatch, transport):
    import aiohttp

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={})

    def unexpected_aio_request(*args, **kwargs):
        raise AssertionError('Unsupported Interactions request reached aiohttp')

    monkeypatch.setattr(aiohttp.ClientSession, 'request', unexpected_aio_request)
    journal = ledger(tmp_path)
    urls = (
        'https://generativelanguage.googleapis.com/v1beta/interactions',
        'https://generativelanguage.googleapis.com/v1/interactions/',
        'https://custom.example/v1beta/%69nteractions',
    )

    async def run():
        with admission.provider_session(journal, seconds=4):
            if transport == 'aiohttp':
                async with aiohttp.ClientSession() as client:
                    for url in urls:
                        with pytest.raises(admission.AdmissionError):
                            client.request('POST', url, json={})
            elif transport == 'sync':
                with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                    for url in urls:
                        with pytest.raises(admission.AdmissionError):
                            client.post(url, json={})
            else:
                async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                    for url in urls:
                        with pytest.raises(admission.AdmissionError):
                            await client.post(url, json={})
                    # Metadata polling remains a read, not an unreserved model creation.
                    await client.get(urls[0] + '/offline-id')

    asyncio.run(run())
    assert len(calls) == (1 if transport == 'async' else 0)
    assert journal.snapshot()['attempts'] == []


def test_pixeltable_computed_graph_records_actual_attempts(tmp_path, monkeypatch, test_video):
    from dataclasses import replace

    from video_benchmark import runner, schema
    from video_benchmark.config import load_config

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=RESPONSE)

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    config = replace(
        load_config({'1', '1L', '2'}),
        vision_sample_keyframes=4,
        frame_select_budget=3,
        gemini_synth_max_images=2,
    )
    journal = ledger(tmp_path)
    with admission.provider_session(journal, seconds=4):
        schema.reset_catalog()
        plan = schema.apply_schema(config, {'1', '1L', '2'})
        _, failed = runner.run_benchmark(plan, str(test_video), 'Describe')
    assert failed == [] and len(calls) == 8
    assert len(journal.snapshot()['attempts']) == 8
    assert journal.snapshot()['unknown_or_pending_attempts'] == 0


def test_preflight_rejects_duration_before_any_catalog_mutation(test_video):
    with pytest.raises(admission.AdmissionError):
        admission.inspect_media([str(test_video)], max_seconds=1)
