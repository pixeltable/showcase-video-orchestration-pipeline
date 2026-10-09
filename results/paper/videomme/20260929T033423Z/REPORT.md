# Video-MME run

- Questions: 123 from 41 videos (seed 42)
- Gemini model: gemini-2.5-flash; Nova model: amazon.nova-lite-v1:0
- Frames: 32 sampled, 24 kept; prices as of 2026-09-28
- Evidence captions: 1312 calls, 1 failed, 0 returned no text
- Evidence transcripts: 41 calls, 0 failed, 1 returned no text

## Accuracy and cost

Cost is billed (with Gemini implicit-cache discounts); list cost prices the same tokens without them.

| Path | n | Accuracy [95% CI] | Short | Medium | Long | $/question | list $/question | $/correct | Failed |
|------|--:|------------------|------:|-------:|-----:|-----------:|------:|----------:|-------:|
| 1 Native Gemini (full video) | 123 | 79.7% [71.7, 85.8] | 100.0% | 74.5% | 71.4% | $0.0608 | $0.1072 | $0.0763 | 6 |
| 1L Native Gemini, low media resolution | 123 | 83.7% [76.2, 89.2] | 100.0% | 78.4% | 78.6% | $0.0397 | $0.0552 | $0.0474 | 6 |
| 2 Orchestrated Gemini (keyframes + ASR + synthesis) | 123 | 79.7% [71.7, 85.8] | 86.7% | 78.4% | 76.2% | $0.0284 | $0.0285 | $0.0357 | 0 |
| 5 Native Amazon Nova (Bedrock) | 123 | 58.5% [49.7, 66.9] | 66.7% | 52.9% | 59.5% | $0.0103 | $0.0103 | $0.0175 | 0 |

## Paired comparisons

Difference intervals resample whole videos; p is the exact McNemar test.

| A vs B | n | Accuracy A - B [95% CI] | A only | B only | McNemar p | Cost A / B |
|--------|--:|------------------------|-------:|-------:|----------:|-----------:|
| 1 vs 1L | 123 | -4.1 pp [-9.8, 1.6] | 4 | 9 | 0.267 | 1.53x |
| 1 vs 2 | 123 | +0.0 pp [-9.8, 9.8] | 14 | 14 | 1.000 | 2.14x |
| 1 vs 5 | 123 | +21.1 pp [9.8, 31.7] | 39 | 13 | 0.000 | 5.93x |
| 1L vs 2 | 123 | +4.1 pp [-4.9, 13.0] | 14 | 9 | 0.405 | 1.39x |
| 1L vs 5 | 123 | +25.2 pp [13.8, 35.8] | 43 | 12 | 0.000 | 3.87x |
| 2 vs 5 | 123 | +21.1 pp [11.4, 30.1] | 36 | 10 | 0.000 | 2.77x |
