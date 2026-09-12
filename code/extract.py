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

VISION_PREFS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-pro", "gemini-2.0-flash"]
TEXT_PREFS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]
GROK_PREFS = ["grok-4-fast", "grok-4", "grok-3"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--messages", action="store_true")
    ap.add_argument("--grok", action="store_true", help="second-opinion message pass via xAI")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--batch", type=int, default=6)
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

    if a.images:
        model = llm.pick(VISION_PREFS, gem)
        print(f"\n[images] model={model}")
        evidence.extract_images(ds, model, refresh=a.refresh)

    if a.messages:
        model = llm.pick(TEXT_PREFS, gem)
        print(f"\n[messages/gemini] model={model}")
        evidence.extract_messages(ds, model, batch=a.batch, refresh=a.refresh, provider="gemini")

    if a.grok:
        xs = llm.xai_models()
        if not xs:
            print("no xAI models visible -- is XAI_API_KEY set and valid?")
        else:
            model = llm.pick(GROK_PREFS, xs)
            print(f"\n[messages/grok] model={model}")
            evidence.extract_messages(ds, model, batch=a.batch, refresh=a.refresh, provider="grok")

    llm.LEDGER.save(evidence.CACHE / "usage.json")
    n = len(llm.LEDGER.calls)
    print(f"\n{n} model calls this session, "
          f"{sum(c.in_tokens for c in llm.LEDGER.calls):,} in / "
          f"{sum(c.out_tokens for c in llm.LEDGER.calls):,} out tokens, "
          f"est ${llm.LEDGER.total_cost():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
