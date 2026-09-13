"""Run the AI evidence passes and cache the results.

    python3 code/extract.py --images --messages
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence  # noqa: E402
import llm       # noqa: E402
import loaders   # noqa: E402

# Free-tier quota is metered per model per day, so the extractor works through
# a pool rather than a single choice. Stronger models first.
POOL = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
    "gemini-flash-latest", "gemini-3-flash-preview",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite-preview",
]
GROK_PREFS = ["grok-4-fast", "grok-4", "grok-3"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--messages", action="store_true")
    ap.add_argument("--grok", action="store_true", help="second-opinion message pass via xAI")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--batch", type=int, default=12)
    a = ap.parse_args()

    llm.load_dotenv()
    ds = loaders.load()
    llm.LEDGER.load(evidence.CACHE / "usage.json")

    gem = llm.gemini_models()
    if a.images or a.messages:
        if not gem:
            print("no Gemini models visible -- is GEMINI_API_KEY set and valid?")
            return 1
        print(f"gemini models visible: {len(gem)}")

    pool = [m for m in POOL if m in gem]
    if a.images:
        print(f"\n[images] pool={pool}")
        evidence.extract_images(ds, pool, refresh=a.refresh)

    if a.messages:
        print(f"\n[messages/gemini] pool={pool}")
        evidence.extract_messages(ds, pool, batch=a.batch, refresh=a.refresh, provider="gemini")

    if a.grok:
        xs = llm.xai_models()
        if not xs:
            print("no xAI models visible -- is XAI_API_KEY set and valid?")
        else:
            model = llm.pick(GROK_PREFS, xs)
            print(f"\n[messages/grok] model={model}")
            evidence.extract_messages(ds, [model], batch=a.batch, refresh=a.refresh, provider="grok")

    llm.LEDGER.save(evidence.CACHE / "usage.json")
    n = len(llm.LEDGER.calls)
    print(f"\n{n} model calls this session, "
          f"{sum(c.in_tokens for c in llm.LEDGER.calls):,} in / "
          f"{sum(c.out_tokens for c in llm.LEDGER.calls):,} out tokens, "
          f"est ${llm.LEDGER.total_cost():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
