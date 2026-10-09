# Golden Pursuit export

All API paths on the Pursuit clip in one run (`20260928T200227Z-d5fc94`, Pixeltable 0.7.11, `gemini-2.5-flash`, prices of 2026-09-28). The showcase page is rendered from it: `python scripts/render_showcase.py`.

| Path | List price | Clip checks |
|------|-----------:|------------:|
| 1 Native Gemini | $0.0371 | 5/5 |
| 1L Native Gemini, low media resolution | $0.0230 | 5/5 |
| 2 Orchestrated Gemini | $0.0320 | 5/5 |
| 4 fal video-understanding (first 120 s) | $0.2400 | 2/5 |
| 5 Amazon Nova Pro | $0.0600 | 1/5 |

`summary.json` holds every answer with its token usage and cost; `keyframes.csv` the 24 captions; `REPORT.md` the readable version. Means over six runs are in [docs/paper/paper.md](../../docs/paper/paper.md).
