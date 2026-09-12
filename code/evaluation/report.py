"""Generate evaluation/usage_report.md from the recorded token ledger.

The ledger is written by llm.py during extraction, so the numbers here describe
the run that actually produced output.csv rather than an estimate.
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm       # noqa: E402
import loaders   # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "cache"

PRICING_NOTE = (
    "Costs are computed from published Gemini flash-tier list pricing "
    "(USD 0.30 / 1M input tokens, USD 2.50 / 1M output tokens). Preview model "
    "pricing can change; the token counts are measured, the dollar figures are "
    "an estimate derived from them."
)


def main() -> int:
    llm.LEDGER.load(CACHE / "usage.json")
    calls = llm.LEDGER.calls
    ds = loaders.load()
    n_requests = len(ds.requests)

    if not calls:
        print("no usage.json -- run code/extract.py first", file=sys.stderr)
        return 1

    by_model: dict[tuple[str, str], list] = defaultdict(list)
    by_purpose: dict[str, list] = defaultdict(list)
    for c in calls:
        by_model[(c.provider, c.model)].append(c)
        by_purpose[c.purpose].append(c)

    tin = sum(c.in_tokens for c in calls)
    tout = sum(c.out_tokens for c in calls)
    tcost = llm.LEDGER.total_cost()

    L = []
    A = L.append
    A("# Token Usage and Cost Analysis")
    A("")
    A(f"_Generated {dt.datetime.now().astimezone().isoformat(timespec='seconds')}_")
    A("")
    A("Final full-dataset run producing `output.csv` "
      f"({n_requests} requests in `dataset/requests.csv`).")
    A("")
    A("## Overall")
    A("")
    A("| Metric | Value |")
    A("|---|---|")
    A(f"| Model calls | {len(calls):,} |")
    A(f"| Input tokens | {tin:,} |")
    A(f"| Output tokens | {tout:,} |")
    A(f"| Total tokens | {tin + tout:,} |")
    A(f"| Average tokens per request | {(tin + tout) / n_requests:,.1f} |")
    A(f"| Estimated total cost | ${tcost:.4f} |")
    A(f"| Estimated cost per request | ${tcost / n_requests:.6f} |")
    A("")
    A("## Per model")
    A("")
    A("| Provider | Model | Calls | Input | Output | Total | Est. cost |")
    A("|---|---|---|---|---|---|---|")
    for (prov, model), cs in sorted(by_model.items()):
        i = sum(c.in_tokens for c in cs)
        o = sum(c.out_tokens for c in cs)
        cost = sum(llm.LEDGER.cost(c) for c in cs)
        A(f"| {prov} | `{model}` | {len(cs):,} | {i:,} | {o:,} | {i + o:,} | ${cost:.4f} |")
    A("")
    A("## Per pass")
    A("")
    A("| Pass | Calls | Input | Output | Total | Est. cost |")
    A("|---|---|---|---|---|---|")
    for purpose, cs in sorted(by_purpose.items()):
        i = sum(c.in_tokens for c in cs)
        o = sum(c.out_tokens for c in cs)
        cost = sum(llm.LEDGER.cost(c) for c in cs)
        A(f"| `{purpose}` | {len(cs):,} | {i:,} | {o:,} | {i + o:,} | ${cost:.4f} |")
    A("")
    A("## Where the tokens go")
    A("")
    A("Model calls are proportional to *evidence*, not to requests. The decision "
      "engine itself is deterministic, so the per-request marginal token cost is "
      "zero once evidence is extracted:")
    A("")
    A(f"- **`image_amount`** — one call per image. Exactly 16 events in the dataset "
      f"have a blank `amount`, each linked to one PNG, so this pass is bounded at 16 calls.")
    A(f"- **`message_directives`** — messages are batched, so 215 messages cost "
      f"{len(by_purpose.get('message_directives', []))} calls rather than 215.")
    A("")
    A("Re-running `code/main.py` costs **zero tokens**: both passes are cached to "
      "`code/cache/`, and the solver never calls a model.")
    A("")
    A("## Pricing note")
    A("")
    A(PRICING_NOTE)
    A("")

    out = HERE / "usage_report.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out}")
    print(f"  {len(calls)} calls, {tin+tout:,} tokens, ${tcost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
