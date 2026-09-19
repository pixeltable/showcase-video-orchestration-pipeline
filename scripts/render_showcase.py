#!/usr/bin/env python3
"""Render a static side-by-side HTML showcase from the golden Pursuit export."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = PROJECT_ROOT / 'results' / 'golden'
DEFAULT_OUT = PROJECT_ROOT / 'docs' / 'showcase.html'


def _clip(text: str, limit: int = 1200) -> str:
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def render(golden_dir: Path) -> str:
    insights = json.loads((golden_dir / 'insights.json').read_text())
    summary = json.loads((golden_dir / 'summary.json').read_text())
    columns = [
        (
            'Path 1 — Native Gemini',
            insights.get('native_insight', ''),
            float(summary.get('native_cost') or 0),
        ),
        (
            'Path 2 — Orchestrated Gemini',
            insights.get('gemini_orchestrated_insight', ''),
            float(summary.get('gemini_orchestrated_total') or 0),
        ),
        (
            'Path 3 — Open source',
            insights.get('oss_insight', ''),
            float(summary.get('oss_cost') or 0),
        ),
    ]
    cards = []
    for title, body, cost in columns:
        cards.append(
            f'<article class="card">'
            f'<h2>{html.escape(title)}</h2>'
            f'<p class="cost">${cost:.3f}</p>'
            f'<pre>{html.escape(_clip(body))}</pre>'
            f'</article>'
        )
    query = html.escape(str(summary.get('query') or ''))
    duration = float(summary.get('video_duration_sec') or 0)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pixeltable video orchestration — showcase</title>
  <style>
    :root {{
      --bg: #0f1419;
      --panel: #1a222c;
      --text: #e8eef4;
      --muted: #9aabbc;
      --accent: #3d9cf0;
      --border: #2a3542;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #1c3a55 0%, transparent 55%),
        radial-gradient(900px 500px at 100% 0%, #243018 0%, transparent 50%),
        var(--bg);
      color: var(--text);
      min-height: 100vh;
    }}
    header {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 2.5rem 1.5rem 1rem;
    }}
    h1 {{
      font-family: "IBM Plex Serif", Georgia, serif;
      font-weight: 600;
      font-size: clamp(1.6rem, 3vw, 2.2rem);
      margin: 0 0 0.5rem;
      letter-spacing: -0.02em;
    }}
    .lede {{
      color: var(--muted);
      max-width: 46rem;
      line-height: 1.5;
      margin: 0;
    }}
    .meta {{
      margin-top: 1rem;
      font-size: 0.9rem;
      color: var(--muted);
    }}
    .grid {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 1rem 1.5rem 3rem;
      display: grid;
      gap: 1rem;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    @media (max-width: 960px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1rem 1.1rem 1.2rem;
      min-height: 18rem;
      animation: rise 0.55s ease both;
    }}
    .card:nth-child(2) {{ animation-delay: 0.08s; }}
    .card:nth-child(3) {{ animation-delay: 0.16s; }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: none; }}
    }}
    h2 {{
      font-size: 1rem;
      margin: 0 0 0.35rem;
      color: var(--accent);
      font-weight: 600;
    }}
    .cost {{
      margin: 0 0 0.75rem;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.78rem;
      line-height: 1.45;
      color: var(--text);
      max-height: 28rem;
      overflow: auto;
    }}
    footer {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 1.5rem 2.5rem;
      color: var(--muted);
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Own the stack</h1>
    <p class="lede">
      Same clip, same question — native Gemini vs modular orchestration vs open source.
      Generated from <code>results/golden/</code>.
    </p>
    <p class="meta">Query: {query}<br />Duration: {duration:.1f}s · tag fair_v1_nova_pro</p>
  </header>
  <section class="grid">
    {''.join(cards)}
  </section>
  <footer>
    Regenerate with <code>python scripts/render_showcase.py</code>.
    Full answers: <code>results/golden/REPORT.md</code>.
  </footer>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--golden',
        type=Path,
        default=DEFAULT_GOLDEN,
        help='Directory with insights.json + summary.json',
    )
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT, help='Output HTML path')
    args = parser.parse_args()
    html_out = render(args.golden)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_out)
    print(f'Wrote {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
