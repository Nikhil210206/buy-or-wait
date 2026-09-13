"""Ablation: which evidence source moves which sample, and in which direction.

Usage: python3 code/evaluation/ablate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence as E   # noqa: E402
import loaders         # noqa: E402
import score as S      # noqa: E402
from ledger import Ledger  # noqa: E402
from solver import solve   # noqa: E402

FIELDS = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method",
          "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]


def run(ds, sds, *, images: bool, messages: bool) -> dict[str, dict]:
    ev = E.load(ds)
    if not images:
        ev.images = {}
    if not messages:
        ev.messages = {}
    led = Ledger(ds, evidence_amounts=ev.image_amounts())
    return {r.request_id: solve(ds, led, r, ev.adjustments_for(led, r.user_id, r.request_date))
            for r in sds.requests}


def main() -> int:
    ds = loaders.load()
    sds = S.sample_dataset(ds)
    gt = {r["request_id"]: r for r in ds.samples}

    variants = {
        "none":     run(ds, sds, images=False, messages=False),
        "images":   run(ds, sds, images=True,  messages=False),
        "messages": run(ds, sds, images=False, messages=True),
        "both":     run(ds, sds, images=True,  messages=True),
    }

    print(f"{'variant':<10}" + "".join(f"{f.split('_')[0][:6]:>9}" for f in FIELDS) + "   total")
    for name, preds in variants.items():
        counts = []
        for f in FIELDS:
            n = sum(1 for rid, g in gt.items()
                    if str(preds[rid].get(f, "")).strip() == g[f].strip())
            counts.append(n)
        print(f"{name:<10}" + "".join(f"{c:>9}" for c in counts) + f"   {sum(counts)}")

    print("\nrequests where 'both' is worse than 'none':")
    for rid, g in gt.items():
        for f in ("affordability_status", "recommended_payment_method"):
            a = str(variants["none"][rid][f]).strip()
            b = str(variants["both"][rid][f]).strip()
            if a == g[f].strip() and b != g[f].strip():
                print(f"  {rid} {f}: none={a} (correct) -> both={b}")
    print("\nrequests where 'both' fixes 'none':")
    for rid, g in gt.items():
        for f in ("affordability_status", "recommended_payment_method"):
            a = str(variants["none"][rid][f]).strip()
            b = str(variants["both"][rid][f]).strip()
            if a != g[f].strip() and b == g[f].strip():
                print(f"  {rid} {f}: none={a} -> both={b} (correct)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
