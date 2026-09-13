# Token Usage and Cost Analysis

_Generated 2026-09-13T15:36:22+05:30_

Final full-dataset run producing `output.csv` (250 requests in `dataset/requests.csv`).

## Overall

| Metric | Value |
|---|---|
| Model calls | 31 |
| Input tokens | 63,160 |
| Output tokens | 26,188 |
| Total tokens | 89,348 |
| Average tokens per request | 357.4 |
| Estimated total cost | $0.0844 |
| Estimated cost per request | $0.000338 |

## Per model

| Provider | Model | Calls | Input | Output | Total | Est. cost |
|---|---|---|---|---|---|---|
| google | `gemini-3.1-flash-lite` | 6 | 8,951 | 543 | 9,494 | $0.0040 |
| google | `gemini-3.5-flash` | 7 | 18,973 | 12,523 | 31,496 | $0.0370 |
| google | `gemini-3.5-flash-lite` | 8 | 20,203 | 12,281 | 32,484 | $0.0368 |
| google | `gemini-3.6-flash` | 10 | 15,033 | 841 | 15,874 | $0.0066 |

## Per pass

| Pass | Calls | Input | Output | Total | Est. cost |
|---|---|---|---|---|---|
| `image_amount` | 16 | 23,984 | 1,384 | 25,368 | $0.0107 |
| `message_directives` | 15 | 39,176 | 24,804 | 63,980 | $0.0738 |

## Where the tokens go

Model calls are proportional to *evidence*, not to requests. The decision engine itself is deterministic, so the per-request marginal token cost is zero once evidence is extracted:

- **`image_amount`** — one call per image. Exactly 16 events in the dataset have a blank `amount`, each linked to one PNG, so this pass is bounded at 16 calls.
- **`message_directives`** — messages are batched, so 215 messages cost 15 calls rather than 215.

Re-running `code/main.py` costs **zero tokens**: both passes are cached to `code/cache/`, and the solver never calls a model.

## Pricing note

Costs are computed from published Gemini flash-tier list pricing (USD 0.30 / 1M input tokens, USD 2.50 / 1M output tokens). Preview model pricing can change; the token counts are measured, the dollar figures are an estimate derived from them.
