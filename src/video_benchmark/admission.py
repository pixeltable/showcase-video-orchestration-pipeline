"""Durable, conservative admission for model transport attempts in managed CLI runs.

The ledger is independent of the catalog transaction: a crash, lost usage, or a later
cell recomputation cannot erase a reservation. It is an estimate, never an invoice.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from video_benchmark import pricing

MAX_OUTPUT_TOKENS = 4096
_managed_lock = threading.Lock()


def safe_response(value):
    """Keep model evidence without secret values or credential-bearing URLs."""
    if isinstance(value, dict):
        return {key: safe_response(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_response(item) for item in value]
    if isinstance(value, str):
        for key in (
            'GOOGLE_API_KEY',
            'GEMINI_API_KEY',
            'FAL_KEY',
            'FAL_API_KEY',
            'HF_TOKEN',
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
            'AWS_SESSION_TOKEN',
        ):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return re.sub(
            r'https?://[^\s<>"\']+', lambda m: urlunsplit((*urlsplit(m.group())[:3], '', '')), value
        )
    return value


class AdmissionError(ValueError):
    """Stop before a model request when its reservation or inputs exceed the policy."""


class AttemptLedger:
    def __init__(self, path: Path, *, budget_usd: float, max_attempts: int = 64):
        if not math.isfinite(budget_usd) or budget_usd <= 0 or max_attempts < 1:
            raise ValueError('Budget must be finite and positive; max attempts must be positive.')
        self.path = path
        self.budget_usd = budget_usd
        self.max_attempts = max_attempts
        self.session_id = uuid.uuid4().hex
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, started REAL NOT NULL, finished REAL,
                state TEXT NOT NULL, reservation_usd REAL NOT NULL, cost_usd REAL,
                response_json TEXT, error_class TEXT
            )""")
        os.chmod(path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, provider: str, model: str, reservation_usd: float) -> str:
        if not math.isfinite(reservation_usd) or reservation_usd <= 0:
            raise AdmissionError('The model request has no valid price reservation.')
        attempt_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            used = db.execute(
                'SELECT COALESCE(SUM(COALESCE(cost_usd,reservation_usd)),0) FROM attempts'
            ).fetchone()[0]
            count = db.execute(
                'SELECT COUNT(*) FROM attempts WHERE session_id=?', (self.session_id,)
            ).fetchone()[0]
            if count >= self.max_attempts or used + reservation_usd > self.budget_usd + 1e-12:
                raise AdmissionError(
                    'Model request blocked before send: the ledger budget or attempt limit is '
                    'exhausted. Unknown attempts keep their reservations. Inspect the ledger '
                    'before explicitly increasing its budget.'
                )
            db.execute(
                'INSERT INTO attempts VALUES (?,?,?,?,?,?,?, ?,NULL,NULL,NULL)',
                (
                    attempt_id,
                    self.session_id,
                    provider,
                    model,
                    time.time(),
                    None,
                    'pending',
                    reservation_usd,
                ),
            )
        return attempt_id

    def finish(
        self,
        attempt_id: str,
        *,
        response: dict | None = None,
        cost_usd: float | None = None,
        error_class: str | None = None,
    ) -> None:
        if cost_usd is not None and (not math.isfinite(cost_usd) or cost_usd < 0):
            raise ValueError('A recorded cost must be finite and nonnegative.')
        with self.connect() as db:
            db.execute(
                'UPDATE attempts SET finished=?,state=?,cost_usd=?,response_json=?, '
                'error_class=? WHERE id=? AND state="pending"',
                (
                    time.time(),
                    'accounted' if cost_usd is not None else 'unknown',
                    cost_usd,
                    json.dumps(safe_response(response), default=str) if response else None,
                    error_class,
                    attempt_id,
                ),
            )

    def snapshot(self) -> dict:
        with self.connect() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY started,id')]
        return {
            'budget_usd': self.budget_usd,
            'session_id': self.session_id,
            'max_attempts_this_session': self.max_attempts,
            'known_response_accounted_cost_usd': sum(row['cost_usd'] or 0 for row in rows),
            'unknown_or_pending_attempts': sum(row['cost_usd'] is None for row in rows),
            'held_unknown_reservation_usd': sum(
                row['reservation_usd'] for row in rows if row['cost_usd'] is None
            ),
            'admission_used_usd': sum(
                row['cost_usd'] if row['cost_usd'] is not None else row['reservation_usd']
                for row in rows
            ),
            'attempts': rows,
            'invoice_reconciled': False,
        }


def inspect_media(
    paths: list[str], *, max_seconds: float = 600.0, require_audio: bool = False
) -> float:
    """Validate every input before applying/resetting a catalog or calling a provider."""
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('The maximum media duration must be finite and positive.')
    import av

    maximum = 0.0
    for path in paths:
        with av.open(path) as media:
            seconds = media.duration / av.time_base if media.duration else 0
            if not media.streams.video or not math.isfinite(seconds) or seconds <= 0:
                raise AdmissionError('Each input must be a readable video with known duration.')
            if seconds > max_seconds:
                raise AdmissionError(
                    f'A video is {seconds:.1f}s, above the {max_seconds:g}s admission limit. '
                    'Choose a shorter clip or explicitly raise --max-media-seconds.'
                )
            if require_audio and not media.streams.audio:
                raise AdmissionError('The selected transcript path requires an audio stream.')
            maximum = max(maximum, seconds)
    return maximum


def request_reservation(provider: str, model: str, payload: dict, seconds: float) -> float:
    """Conservative input envelope; provider billing can differ from these assumptions."""
    if provider == 'fal':
        return pricing.fal_cost_impl(seconds, 120.0)
    if provider == 'bedrock':
        rates = pricing.nova_model_rates(model)
        return (
            max(1000, math.ceil(seconds * 1500)) * rates[0] + MAX_OUTPUT_TOKENS * rates[1]
        ) / 1e6
    if model not in pricing.GEMINI_RATES:
        raise AdmissionError('This Gemini model has no price snapshot.')
    rates = pricing.GEMINI_RATES[model]
    # Text reserves one token per character. Each image reserves 4096 tokens; video
    # reserves 1000 tokens/second and audio100. These are admission assumptions.
    counts = {'TEXT': 0, 'IMAGE': 0, 'VIDEO': 0, 'AUDIO': 0}
    for content in payload.get('contents', []):
        for part in content.get('parts', []):
            counts['TEXT'] += len(part.get('text', ''))
            blob = part.get('inlineData') or part.get('inline_data') or part.get('fileData') or {}
            mime = blob.get('mimeType', blob.get('mime_type', ''))
            if mime.startswith('image/'):
                counts['IMAGE'] += 4096
            elif mime.startswith('video/'):
                counts['VIDEO'] += math.ceil(seconds * 1000)
                counts['AUDIO'] += math.ceil(seconds * 100)
            elif mime.startswith('audio/'):
                counts['AUDIO'] += math.ceil(seconds * 100)
    return (
        sum(counts[name] * rates.input[name] for name in counts) + MAX_OUTPUT_TOKENS * rates.output
    ) / 1e6


def model_request(request) -> tuple[str, str] | None:
    """Only charge model POSTs, never uploads, metadata reads, or queue polling."""
    url = urlsplit(str(request.url))
    if request.method != 'POST':
        return None
    if url.hostname == 'generativelanguage.googleapis.com' and url.path.endswith(
        ':generateContent'
    ):
        return 'gemini', unquote(url.path.rsplit('/models/', 1)[-1].split(':', 1)[0])
    if url.hostname == 'queue.fal.run' and url.path.strip('/') == 'fal-ai/video-understanding':
        return 'fal', 'fal-ai/video-understanding'
    return None


def add_arguments(parser) -> None:
    parser.add_argument(
        '--budget-usd',
        type=float,
        default=1.0,
        help='Accounted + unresolved reservation ceiling for this ledger (default $1)',
    )
    parser.add_argument(
        '--max-attempts',
        type=int,
        default=64,
        help='Maximum actual model requests in this invocation, including retries',
    )
    parser.add_argument(
        '--max-media-seconds',
        type=float,
        default=600.0,
        help='Reject longer media before catalog changes (default 600 seconds)',
    )
    parser.add_argument(
        '--ledger',
        type=str,
        default=None,
        help='Durable attempt ledger (default results/provider-ledger.sqlite3)',
    )
    parser.add_argument(
        '--preflight',
        action='store_true',
        help='Inspect local inputs, effective paths and admission; no model calls',
    )


def validate_arguments(args) -> None:
    if (
        not math.isfinite(args.budget_usd)
        or args.budget_usd <= 0
        or args.max_attempts < 1
        or not math.isfinite(args.max_media_seconds)
        or args.max_media_seconds <= 0
    ):
        raise ValueError(
            'Budget and media duration must be finite and positive; attempts at least 1.'
        )


def export_snapshot(ledger: AttemptLedger, out: Path) -> None:
    (out / 'provider-attempts.json').write_text(json.dumps(ledger.snapshot(), indent=2) + '\n')


@contextmanager
def provider_session(ledger: AttemptLedger, *, seconds: float, bedrock_enabled: bool = False):
    """Attach bounded actual-send guards while leaving Pixeltable provider UDFs intact.

    The adapters instrument HTTPX and botocore transport send methods. No Pixeltable
    client getters or media internals are replaced. Only one managed run owns these hooks.
    """
    import aiohttp
    import httpx
    from botocore.httpsession import URLLib3Session
    from google import genai
    from google.genai import types

    if not _managed_lock.acquire(blocking=False):
        raise AdmissionError('Another managed provider run is already active in this process.')
    original_send = httpx.AsyncClient.send
    original_sync_send = httpx.Client.send
    original_aio_request = aiohttp.ClientSession.request
    original_genai_init = genai.Client.__init__
    original_bedrock_send = URLLib3Session.send
    previous_attempts = os.environ.get('AWS_MAX_ATTEMPTS')
    os.environ['AWS_MAX_ATTEMPTS'] = '1'

    def unsupported_model(method, url):
        parsed = urlsplit(str(url))
        return method.upper() == 'POST' and (
            ':generateContent' in parsed.path
            or '/models/' in parsed.path
            or parsed.hostname in {'queue.fal.run', 'fal.run'}
        )

    def sync_send(client, request, *args, **kwargs):
        if unsupported_model(request.method, request.url):
            raise AdmissionError(
                'Synchronous model transports are unsupported in this managed run.'
            )
        return original_sync_send(client, request, *args, **kwargs)

    def aio_request(client, method, url, *args, **kwargs):
        if unsupported_model(method, url):
            raise AdmissionError(
                'Existing aiohttp model clients are unsupported; use a fresh CLI process.'
            )
        return original_aio_request(client, method, url, *args, **kwargs)

    def genai_init(client, *args, **kwargs):
        # Public Client/HttpOptions configuration selects the guarded HTTP transport.
        # Current google-genai defaults to aiohttp when installed; do not bypass the guard.
        supplied = kwargs.get('http_options') or {}
        options = (
            supplied if isinstance(supplied, types.HttpOptions) else types.HttpOptions(**supplied)
        )
        kwargs['http_options'] = options.model_copy(
            update={
                'async_client_args': {'transport': httpx.AsyncHTTPTransport()},
                'httpx_async_client': None,
                'retry_options': types.HttpRetryOptions(attempts=1),
                'timeout': 60_000,
            }
        )
        return original_genai_init(client, *args, **kwargs)

    async def send(client, request, *args, **kwargs):
        target = model_request(request)
        if target is None:
            if unsupported_model(request.method, request.url):
                raise AdmissionError('This model endpoint is not supported by the admission guard.')
            return await original_send(client, request, *args, **kwargs)
        provider, model = target
        payload = json.loads(request.content)
        if provider == 'gemini':
            cap = (payload.get('generationConfig') or {}).get('maxOutputTokens')
            if not isinstance(cap, int) or not 1 <= cap <= MAX_OUTPUT_TOKENS:
                raise AdmissionError('Gemini output must be bounded before the model request.')
        attempt = ledger.reserve(
            provider, model, request_reservation(provider, model, payload, seconds)
        )
        try:
            response = await original_send(client, request, *args, **kwargs)
            await response.aread()
            raw = response.json()
            cost = None
            if response.is_success:
                try:
                    cost = (
                        pricing.gemini_cost_impl(pricing.gemini_usage_impl(raw), model)
                        if provider == 'gemini'
                        else pricing.fal_cost_impl(seconds, 120.0)
                    )
                except (ValueError, TypeError, KeyError):
                    pass  # successful text can still have unknown accounting
            # Store only model outputs/usage: never the request, headers, keys, or URLs.
            stored = (
                {
                    key: raw.get(key)
                    for key in (
                        'candidates',
                        'usageMetadata',
                        'usage_metadata',
                        'promptFeedback',
                        'prompt_feedback',
                        'responseId',
                    )
                }
                if provider == 'gemini'
                else {'accepted': response.is_success, 'request_id': raw.get('request_id')}
            )
            ledger.finish(
                attempt,
                response=stored,
                cost_usd=cost,
                error_class=None if response.is_success else f'HTTP{response.status_code}',
            )
            return response
        except BaseException as exc:
            ledger.finish(attempt, error_class=type(exc).__name__)
            raise

    def bedrock_send(client, request):
        parsed_url = urlsplit(request.url)
        if request.method != 'POST' or '/model/' not in parsed_url.path:
            return original_bedrock_send(client, request)
        region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
        if (not bedrock_enabled or not parsed_url.path.endswith('/converse')
                or parsed_url.hostname != f'bedrock-runtime.{region}.amazonaws.com'):
            raise AdmissionError(
                'This Bedrock model endpoint is unsupported by the admission guard.'
            )
        payload = json.loads(request.body)
        cap = payload.get('inferenceConfig', {}).get('maxTokens')
        if not isinstance(cap, int) or not 1 <= cap <= MAX_OUTPUT_TOKENS:
            raise AdmissionError('Nova output must be bounded before the model request.')
        model = unquote(parsed_url.path.split('/model/', 1)[-1].split('/converse')[0])
        attempt = ledger.reserve(
            'bedrock', model, request_reservation('bedrock', model, payload, seconds)
        )
        try:
            response = original_bedrock_send(client, request)
            raw = json.loads(response.content)
            cost = None
            if 200 <= response.status_code < 300:
                try:
                    cost = pricing.nova_cost_impl(pricing.nova_usage_impl(raw), model)
                except (ValueError, TypeError, KeyError):
                    pass
            ledger.finish(
                attempt,
                response={key: raw.get(key) for key in ('output', 'usage', 'stopReason')},
                cost_usd=cost,
                error_class=None if response.status_code < 300 else f'HTTP{response.status_code}',
            )
            return response
        except BaseException as exc:
            ledger.finish(attempt, error_class=type(exc).__name__)
            raise

    httpx.AsyncClient.send = send
    httpx.Client.send = sync_send
    aiohttp.ClientSession.request = aio_request
    genai.Client.__init__ = genai_init
    URLLib3Session.send = bedrock_send
    try:
        yield ledger
    finally:
        httpx.AsyncClient.send = original_send
        httpx.Client.send = original_sync_send
        aiohttp.ClientSession.request = original_aio_request
        genai.Client.__init__ = original_genai_init
        URLLib3Session.send = original_bedrock_send
        if previous_attempts is None:
            os.environ.pop('AWS_MAX_ATTEMPTS', None)
        else:
            os.environ['AWS_MAX_ATTEMPTS'] = previous_attempts
        _managed_lock.release()
