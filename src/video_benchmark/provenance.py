"""Content identities for reproducible exports, independent of catalog and provider calls."""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path


def media_identity(path: str | Path) -> dict:
    media = Path(path)
    digest = hashlib.sha256()
    with media.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'sha256': digest.hexdigest(), 'bytes': media.stat().st_size}


def input_identity(payload: dict) -> str:
    """Canonical identity of accepted inputs; file identity is supplied as a bytes digest."""
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode()).hexdigest()


def source_identity() -> str:
    """Hash the package source including uncommitted edits, with stable relative paths."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for source in sorted(root.rglob('*.py')):
        digest.update(source.relative_to(root).as_posix().encode() + b'\0')
        digest.update(source.read_bytes() + b'\0')
    return digest.hexdigest()


def package_versions() -> dict[str, str]:
    versions = {}
    for name in ('pixeltable', 'google-genai', 'av', 'scenedetect', 'numpy', 'boto3',
                 'fal-client', 'llama-cpp-python', 'openai-whisper', 'whisperx', 'datasets'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return versions


def pipeline_identity(config: dict, paths: list[str], sdk_version: str) -> str:
    """Freeze benchmark computation, including UDF bodies schema diff cannot inspect."""
    root = Path(__file__).resolve().parent
    names = (
        'accounting.py', 'config.py', 'schema.py', 'evidence.py', 'oss.py', 'pricing.py',
        'prompts.py', 'providers.py', 'videomme/schema.py', 'videomme/prompts.py',
        'videomme/scoring.py',
    )
    digest = hashlib.sha256(json.dumps(
        {'config': config, 'paths': sorted(paths), 'sdk': sdk_version}, sort_keys=True
    ).encode())
    for name in names:
        digest.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    return digest.hexdigest()
