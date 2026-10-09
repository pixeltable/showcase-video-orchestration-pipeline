#!/usr/bin/env python3
"""Render an inspectable comparison from saved results, without making provider calls."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = PROJECT_ROOT / 'results' / 'golden'
DEFAULT_OUT = PROJECT_ROOT / 'docs' / 'showcase.html'
CLIP_CHECKS = ('nice_pants', 'jay', 'chris', 'salary', 'tonight')
REPOSITORY = 'https://github.com/pixeltable/showcase-video-orchestration-pipeline'


def _money(value: float | None) -> str:
    return 'n/a' if value is None else f'${value:.4f}'


def render(golden_dir: Path) -> str:
    summary = json.loads((golden_dir / 'summary.json').read_text())
    manifest_path = golden_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    answers = []
    comparison_rows = []
    for path, entry in summary['paths'].items():
        hits = sum(1 for check in CLIP_CHECKS if entry['scores'].get(check))
        # Results are untrusted model output. Keep them as escaped text, including Markdown.
        label = html.escape(entry['label'])
        anchor = f'path-{html.escape(path, quote=True)}'
        comparison_rows.append(
            f'<tr><th scope="row"><a href="#{anchor}">{label}</a></th>'
            f'<td>{_money(entry.get("list_cost_usd"))}</td>'
            f'<td>{_money(entry.get("cost_usd"))}</td>'
            f'<td>{hits}/{len(CLIP_CHECKS)}</td><td>{entry["words"]}</td></tr>'
        )
        stages = []
        for name, stage in entry.get('stages', {}).items():
            stage_cost = _money(stage.get('cost_usd'))
            if (
                stage.get('cost_usd') is None
                and stage.get('response_accounted_cost_usd') is not None
            ):
                subtotal = _money(stage['response_accounted_cost_usd'])
                stage_cost += f' ({subtotal} known subtotal)'
            stages.append(
                f'<tr><th scope="row">{html.escape(name)}</th>'
                f'<td>{stage.get("calls", "n/a")}</td>'
                f'<td>{stage.get("failed_calls", "n/a")}</td>'
                f'<td>{stage.get("unknown_cost_calls", 0)}</td>'
                f'<td>{stage_cost}</td></tr>'
            )
        stage_table = (
            (
                '<div class="table-scroll" role="region" '
                'aria-label="Stage accounting" tabindex="0">'
                '<table><caption>Saved stage accounting</caption><thead><tr>'
                '<th scope="col">Stage</th><th scope="col">Calls</th>'
                '<th scope="col">Failed cells</th><th scope="col">Unknown cost calls</th>'
                '<th scope="col">Cost estimate</th>'
                f'</tr></thead><tbody>{"".join(stages)}</tbody></table></div>'
            )
            if stages
            else ''
        )
        errors = entry.get('errors') or {}
        escaped_errors = html.escape(json.dumps(errors, ensure_ascii=False))
        error_note = f'<p class="error">Recorded errors: {escaped_errors}</p>' if errors else ''
        answers.append(
            f'<article id="{anchor}">'
            f'<h3>{label}</h3>'
            f'<p class="cost">{_money(entry.get("list_cost_usd"))} list, '
            f'{_money(entry.get("cost_usd"))} response-accounted · {entry["words"]} words · '
            f'{hits}/{len(CLIP_CHECKS)} phrase checks</p>'
            f'{stage_table}{error_note}<details><summary>Read the saved answer</summary>'
            f'<pre>{html.escape(entry["answer"] or "(no answer)")}</pre></details>'
            '</article>'
        )
    query = html.escape(summary['query'])
    duration = float(summary['duration_sec'] or 0)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video orchestration showcase</title>
  <style>
    :root {{
      --bg: #fcfcfb; --panel: #ffffff; --text: #0b0b0b; --muted: #52514e;
      --accent: #185da8; --border: #e4e3df; --error: #9e302c; color-scheme: light;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #1a1a19; --panel: #232322; --text: #ffffff; --muted: #c3c2b7;
        --accent: #86baff; --border: #383835; --error: #ffa7a0; color-scheme: dark;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--text);
    }}
    header, main, footer {{ max-width: 1040px; margin: 0 auto; padding: 1.5rem 24px; }}
    header {{ padding-top: 3rem; }}
    h1 {{ font-size: clamp(1.7rem, 4vw, 2.5rem); line-height: 1.15; margin: 0 0 1rem; }}
    h2 {{ font-size: 1.5rem; margin: 0 0 1rem; }}
    h3 {{ font-size: 1.15rem; margin: 0 0 0.5rem; }}
    p {{ max-width: 72ch; line-height: 1.6; overflow-wrap: anywhere; }}
    .meta, footer, .cost, caption {{ color: var(--muted); }}
    nav {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; }}
    nav a, summary {{ min-height: 44px; display: inline-flex; align-items: center; }}
    a {{ color: var(--accent); text-underline-offset: 0.2em; }}
    :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 4px; }}
    ::selection {{ background: var(--accent); color: var(--bg); }}
    section {{ margin-bottom: 3rem; }}
    .flow {{ display: grid; grid-template-columns: repeat(4, 1fr); padding: 0;
             list-style-position: inside; gap: 1.25rem; }}
    .flow li {{ border-top: 1px solid var(--border); padding-top: 1rem; line-height: 1.6; }}
    .flow span {{ display: block; margin-top: 0.35rem; color: var(--muted); }}
    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    caption {{ text-align: left; padding-bottom: 0.75rem; }}
    td, th {{ padding: 0.8rem 0.6rem; border-bottom: 1px solid var(--border); text-align: left; }}
    td {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
    th:first-child {{ min-width: 180px; }}
    article {{ border-top: 1px solid var(--border); padding: 1.5rem 0; scroll-margin-top: 1rem; }}
    .cost {{ font-size: 0.9rem; font-variant-numeric: tabular-nums; }}
    summary {{ cursor: pointer; color: var(--accent); text-decoration: underline;
               text-underline-offset: 0.2em; }}
    summary::before {{ content: '+ '; margin-inline-end: 0.5rem; }}
    details[open] summary::before {{ content: '− '; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 1rem;
          line-height: 1.65; max-width: 75ch; padding: 1rem 0; margin: 0; }}
    .error {{ color: var(--error); }}
    @media (max-width: 600px) {{
      header, main, footer {{ padding-inline: 16px; }}
      header {{ padding-top: 2rem; }}
      .flow {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Video orchestration you can inspect.</h1>
    <p>Compare a native video call with a pipeline of keyframes, audio, captions, and synthesis.
      Pixeltable stores the media and computed results together, so you can inspect evidence,
      change a transform, and query the result through the SDK.</p>
    <nav aria-label="Showcase resources">
      <a href="{REPOSITORY}">Run the showcase</a>
      <a href="{REPOSITORY}/blob/main/src/video_benchmark/schema.py">Inspect the pipeline</a>
      <a href="{REPOSITORY}/blob/main/docs/WORKFLOW.md">Reproduce the experiment</a>
    </nav>
    <p class="meta">
      Saved question: {query}<br />
      Video: {duration:.1f} s · run {html.escape(summary['run_id'])}<br />
      Recorded SDK: Pixeltable
      {html.escape(str(manifest.get('pixeltable_version', 'not recorded')))} ·
      exported {html.escape(str(manifest.get('exported_utc', 'not recorded')))}
    </p>
  </header>
  <main>
    <section aria-labelledby="pipeline-title">
      <h2 id="pipeline-title">What the modular path keeps</h2>
      <ol class="flow">
        <li><strong>Source video</strong><span>A typed video column and scene cuts.</span></li>
        <li><strong>Media views</strong><span>Sampled images and audio chunks.</span></li>
        <li><strong>Evidence</strong><span>Frame captions and a reusable transcript.</span></li>
        <li><strong>Answers</strong>
          <span>Synthesis, usage, errors, and cost expressions.</span></li>
      </ol>
    </section>
    <section aria-labelledby="comparison-title">
      <h2 id="comparison-title">One clip, one question, every saved path</h2>
      <div class="table-scroll" role="region" aria-label="Saved path comparison" tabindex="0">
        <table><caption>Recorded results from this clip;
          phrase checks are diagnostics, not a quality benchmark.</caption>
          <thead><tr><th scope="col">Path</th><th scope="col">List estimate</th>
            <th scope="col">Response-accounted</th><th scope="col">Phrase checks</th>
            <th scope="col">Words</th></tr></thead>
          <tbody>{''.join(comparison_rows)}</tbody>
        </table>
      </div>
      <p class="meta">The fal path sees only the first 120 seconds. Other paths use the full clip or
        sampled evidence from it. Inspect the answers before comparing their coverage.</p>
    </section>
    <section aria-labelledby="answers-title">
      <h2 id="answers-title">Inspect answers and stage accounting</h2>
      {''.join(answers)}
    </section>
  </main>
  <footer>
    <p>These are saved outputs, not a fresh run on the upgraded SDK.
      List estimates exclude cache discounts;
      response-accounted estimates include reported discounts.
      Neither is an invoice total: unrecorded retry or failed-request charges, local compute,
      storage, and egress are excluded. This page makes no API calls.</p>
  </footer>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--golden', type=Path, default=DEFAULT_GOLDEN, help='Run export directory')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT, help='Output HTML path')
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.golden))
    print(f'Wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
