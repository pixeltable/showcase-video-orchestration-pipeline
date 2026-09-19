#!/usr/bin/env python3
"""Expand pipeline_analytics.ipynb with full DAG visibility (idempotent)."""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / 'notebooks' / 'pipeline_analytics.ipynb'


def cell(cell_type: str, source: str, cell_id: str | None = None) -> dict:
    c: dict = {'cell_type': cell_type, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if cell_id:
        c['id'] = cell_id
    if cell_type == 'code':
        c['execution_count'] = None
        c['outputs'] = []
    return c


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text())
    # Drop stale outputs from prior runs.
    for c in nb.get('cells', []):
        if c.get('cell_type') == 'code':
            c['outputs'] = []
            c['execution_count'] = None

    cells = [
        cell(
            'markdown',
            '# Pipeline Analytics\n\n'
            '**Kernel:** use `video-benchmark` (launch via `./scripts/notebook.sh`). '
            'Do not use the conda `pxt` env.\n\n'
            'After code changes, run `run-benchmark --reset` once so catalog columns match '
            'the installed package.\n',
            'intro',
        ),
        cell(
            'code',
            'import json\n'
            'import re\n'
            'import sys\n'
            'from pathlib import Path\n\n'
            'import matplotlib.pyplot as plt\n'
            'import pixeltable as pxt\n\n'
            '# --- KERNEL CHECK ---\n'
            "print('python:', sys.executable)\n"
            "print('pixeltable:', pxt.__version__)\n"
            "if '.venv' not in sys.executable:\n"
            "    print('WARNING: select the video-benchmark kernel (.venv), not conda pxt')\n"
            "if not str(pxt.__version__).startswith('0.7.'):\n"
            "    print('WARNING: expected pixeltable 0.7.x; run ./scripts/notebook.sh')\n\n"
            "pxt.ls('video_benchmarking')\n",
            'setup',
        ),
        cell(
            'markdown',
            '## Pipeline map\n\n'
            'Catalog DAG (see [docs/WORKFLOW.md](../docs/WORKFLOW.md)):\n\n'
            '`video_sources` → `keyframes` (fps sample when scene-aware) + `audio_chunks` (ASR) '
            '→ dedupe → select → summarize → (Path 3 compact) → assembled context → synthesis.\n',
            'pipeline-map',
        ),
        cell(
            'code',
            "vs = pxt.get_table('video_benchmarking.video_sources')\n"
            "keyframes = pxt.get_table('video_benchmarking.keyframes')\n"
            "audio = pxt.get_table('video_benchmarking.audio_chunks')\n",
            'handles',
        ),
        cell('code', 'vs.describe()\n', 'describe'),
        cell('markdown', '## 1 — Segmentation\n', 'sec-seg'),
        cell('code', 'vs.select(vs.scene_cuts, vs.segment_times).tail(1)\n', 'scene-cuts'),
        cell(
            'code',
            'vs.select(vs.segment_times).tail(1)\n',
            'segment-timeline',
        ),
        cell('markdown', '## 2 — Vision (keyframes)\n', 'sec-vision'),
        cell(
            'code',
            'keyframes.select(\n'
            '    keyframes.global_position_ms,\n'
            '    keyframes.gemini_frame_insight,\n'
            '    keyframes.oss_frame_insight,\n'
            ').order_by(keyframes.global_position_ms).limit(8).collect()\n',
            'kf-compare',
        ),
        cell(
            'code',
            'keyframes.select(\n'
            '    keyframes.frame,\n'
            '    keyframes.gemini_frame_insight,\n'
            '    keyframes.oss_frame_insight,\n'
            ').order_by(keyframes.global_position_ms).limit(1).collect()\n',
            'kf-frame',
        ),
        cell('markdown', '## 3 — ASR (audio chunks)\n', 'sec-asr'),
        cell(
            'code',
            'cols = list(audio.columns)\n'
            'asr_cols = [c for c in cols if any(k in c for k in (\n'
            "    'gemini_transcript', 'whisperx_segment', 'whisper_segment', 'gemini_chunk'\n"
            '))]\n'
            'print("ASR-related columns:", asr_cols)\n'
            'sel = [getattr(audio, c) for c in asr_cols[:4]]\n'
            'asr = audio.select(\n'
            '    audio.segment_start, *sel\n'
            ').order_by(audio.segment_start).collect()\n'
            'print(f"chunks: {len(asr)}")\n'
            'row0 = asr[0] if asr else {}\n'
            'for c in asr_cols:\n'
            '    if c not in row0:\n'
            '        continue\n'
            '    v = row0[c]\n'
            '    if isinstance(v, list):\n'
            '        print(f"{c}: {len(v)} lines; sample={v[:2]}")\n'
            '    else:\n'
            '        preview = str(v)[:200] if v is not None else None\n'
            '        print(f"{c}: {preview}")\n',
            'asr-chunks',
        ),
        cell('markdown', '## 4 — Intermediate context (parent table)\n', 'sec-intermediate'),
        cell(
            'code',
            'labels = [\n'
            '    "gemini_frame_context",\n'
            '    "gemini_frame_context_deduped",\n'
            '    "gemini_frame_context_selected",\n'
            '    "gemini_frame_context_summarized",\n'
            '    "oss_frame_context",\n'
            '    "oss_frame_context_deduped",\n'
            '    "oss_frame_context_selected",\n'
            '    "oss_frame_context_summarized",\n'
            '    "oss_frame_context_compact",\n'
            '    "gemini_transcript_context",\n'
            '    "oss_transcript_context",\n'
            ']\n'
            'available = [n for n in labels if hasattr(vs, n)]\n'
            'ctx_counts = vs.select(\n'
            '    *[getattr(vs, n) for n in available]\n'
            ').tail(1).to_pandas().iloc[0]\n'
            'for name in available:\n'
            '    val = ctx_counts[name]\n'
            '    n = len(val) if isinstance(val, list) else 0\n'
            '    print(f"{name}: {n}")\n'
            '    if name == "oss_frame_context_compact" and isinstance(val, list) and val:\n'
            '        chars = [\n'
            '            len(str(item.get("frame_insight", "")))\n'
            '            for item in val if isinstance(item, dict)\n'
            '        ]\n'
            '        mean_c = sum(chars) / len(chars)\n'
            '        print(\n'
            '            f"  compact insight chars: "\n'
            '            f"min={min(chars)} max={max(chars)} mean={mean_c:.0f}"\n'
            '        )\n',
            'ctx-counts',
        ),
        cell('markdown', '## 5 — Assembly (synthesis inputs)\n', 'sec-assembly'),
        cell(
            'code',
            'def _block(text, tag):\n'
            '    if not text:\n'
            '        return ""\n'
            '    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.S)\n'
            '    return (m.group(1).strip() if m else "")\n\n'
            'asm = vs.select(\n'
            '    vs.gemini_orchestrated_context,\n'
            '    vs.oss_context,\n'
            '    vs.oss_synthesis_prompt_text,\n'
            ').tail(1).to_pandas().iloc[0]\n\n'
            'for label, col in [\n'
            '    ("Gemini orchestrated", "gemini_orchestrated_context"),\n'
            '    ("OSS", "oss_context"),\n'
            ']:\n'
            '  text = asm[col] or ""\n'
            '  audio = _block(text, "audio_transcript")\n'
            '  visual = _block(text, "visual_keyframe_timeline")\n'
            '  print(f"=== {label} ===")\n'
            '  print("audio lines:", len([ln for ln in audio.splitlines() if ln.strip()]))\n'
            '  print("visual preview:", (visual[:240] + "...") if visual else "N/A")\n'
            '  print()\n\n'
            'prompt = asm["oss_synthesis_prompt_text"] or ""\n'
            'print("oss_synthesis_prompt_text chars:", len(prompt))\n'
            'print(prompt[:500], "...")\n',
            'assembly',
        ),
        cell('markdown', '## 6 — Rollups and cost breakdown\n', 'sec-rollups'),
        cell(
            'code',
            'rollup = vs.select(\n'
            '    vs.gemini_vision_rollup,\n'
            '    vs.native_cost,\n'
            '    vs.gemini_vision_track_cost,\n'
            '    vs.gemini_asr_cost,\n'
            '    vs.gemini_synthesis_cost,\n'
            '    vs.gemini_orchestrated_total,\n'
            '    vs.oss_cost,\n'
            ').tail(1).to_pandas().iloc[0]\n\n'
            'print("gemini_vision_rollup:", rollup["gemini_vision_rollup"])\n'
            'print(\n'
            '    "costs | native:", rollup["native_cost"],\n'
            '    "| gemini total:", rollup["gemini_orchestrated_total"],\n'
            '    "| vision:", rollup["gemini_vision_track_cost"],\n'
            '    "| asr:", rollup["gemini_asr_cost"],\n'
            '    "| synth:", rollup["gemini_synthesis_cost"],\n'
            '    "| oss:", rollup["oss_cost"],\n'
            ')\n',
            'rollups',
        ),
        cell('markdown', '## 7 — Final insights\n', 'sec-final'),
        cell(
            'code',
            'vs.select(\n'
            '    vs.query,\n'
            '    vs.video_duration_sec,\n'
            '    vs.native_insight,\n'
            '    vs.gemini_orchestrated_insight,\n'
            '    vs.oss_insight,\n'
            '    vs.native_cost,\n'
            '    vs.gemini_orchestrated_total,\n'
            '    vs.oss_cost,\n'
            ').tail(1)\n',
            'final-row',
        ),
        cell(
            'code',
            'insights = vs.select(\n'
            '    vs.native_insight,\n'
            '    vs.gemini_orchestrated_insight,\n'
            '    vs.oss_insight,\n'
            ').tail(1)\n\n'
            "for col in ['native_insight', 'gemini_orchestrated_insight', 'oss_insight']:\n"
            "    print('=' * 64)\n"
            '    print(col)\n'
            '    print(insights[col][0])\n'
            '    print()\n',
            'print-insights',
        ),
        cell(
            'code',
            '# Narrative quality comparison\n'
            'row = vs.select(\n'
            '    vs.native_insight,\n'
            '    vs.gemini_orchestrated_insight,\n'
            '    vs.oss_insight,\n'
            '    vs.gemini_transcript_context,\n'
            '    vs.oss_transcript_context,\n'
            '    vs.video_duration_sec,\n'
            ').tail(1).to_pandas().iloc[0]\n\n'
            'paths = ["native_insight", "gemini_orchestrated_insight", "oss_insight"]\n'
            'for col in paths:\n'
            '    text = str(row[col] or "")\n'
            '    bullets = text.count("**") // 2\n'
            '    numbered = sum(\n'
            '        1 for line in text.splitlines() if line.strip()[:2].rstrip(".").isdigit()\n'
            '    )\n'
            '    print(\n'
            '        f"{col}: {len(text.split())} words, "\n'
            '        f"{bullets} bold sections, {numbered} numbered lines"\n'
            '    )\n'
            '    preview = text[:200].replace(chr(10), " ")\n'
            '    print(f"  preview: {preview}...")\n'
            '    print()\n\n'
            'print("gemini transcript chunks:", len(row["gemini_transcript_context"] or []))\n'
            'print("oss transcript chunks:", len(row["oss_transcript_context"] or []))\n'
            'print("video duration (s):", row["video_duration_sec"])\n\n'
            'kf = keyframes.select(keyframes.global_position_ms).order_by(\n'
            '    keyframes.global_position_ms\n'
            ').collect()\n'
            'positions = [r["global_position_ms"] / 1000.0 for r in kf]\n'
            'print(f"keyframes sampled: {len(positions)}")\n'
            'if positions:\n'
            '    fig, ax = plt.subplots(figsize=(8, 2))\n'
            '    ax.scatter(positions, [1] * len(positions), alpha=0.6)\n'
            '    ax.set_xlim(0, float(row["video_duration_sec"] or max(positions)))\n'
            '    ax.set_xlabel("seconds")\n'
            '    ax.set_title("Keyframe sampling across video timeline")\n'
            '    ax.set_yticks([])\n'
            '    plt.tight_layout()\n'
            '    plt.show()\n',
            'narrative',
        ),
        cell(
            'code',
            'costs = vs.select(\n'
            '    vs.native_cost,\n'
            '    vs.gemini_orchestrated_total,\n'
            '    vs.oss_cost,\n'
            ').tail(1).to_pandas().iloc[0]\n\n'
            "fig, ax = plt.subplots(figsize=(7, 4))\n"
            "labels = ['Native', 'Gemini', 'OSS']\n"
            "values = [\n"
            "    costs['native_cost'],\n"
            "    costs['gemini_orchestrated_total'],\n"
            "    costs['oss_cost'],\n"
            "]\n"
            'ax.bar(labels, values)\n'
            "ax.set_ylabel('USD')\n"
            "ax.set_title('Three-path costs')\n"
            'plt.show()\n',
            'cost-bar',
        ),
        cell(
            'code',
            "export_dirs = sorted(Path('results').glob('*/summary.json'))\n"
            'if export_dirs:\n'
            '    latest = export_dirs[-1]\n'
            '    print("latest export:", latest.parent)\n'
            '    print(json.loads(latest.read_text()))\n'
            'else:\n'
            "    print('No results/ exports yet — run run-benchmark')\n",
            'export',
        ),
        cell(
            'code',
            'vs.where(vs.native_insight.errortype != None).select(\n'
            '    vs.query, vs.native_insight.errortype, vs.native_insight.error_msg,\n'
            ').collect()\n',
            'errors',
        ),
        cell('code', '!pxt dashboard\n', 'dashboard'),
    ]

    nb['cells'] = cells
    nb['metadata'].setdefault('kernelspec', {})['display_name'] = 'video-benchmark'
    NOTEBOOK.write_text(json.dumps(nb, indent=1) + '\n')
    print(f'Wrote {len(cells)} cells to {NOTEBOOK}')


if __name__ == '__main__':
    main()
