"""Self-scoring harness: run the pipeline over the 25 solved samples.

Two modes:
  --check-gt  run the ground-truth sample rows through verify.py. This validates
              our reading of the output contract: if the official answers fail
              our verifier, the verifier is wrong.
  (default)   run our solver over the samples and report per-field accuracy.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import loaders          # noqa: E402
import verify           # noqa: E402
from loaders import Dataset, Request  # noqa: E402

FIELDS = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method",
          "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]


def sample_requests(ds: Dataset) -> list[Request]:
    out = []
    for r in ds.samples:
        out.append(Request(
            request_id=r["request_id"], user_id=r["user_id"],
            request_date=dt.date.fromisoformat(r["request_date"]),
            request_type=r["request_type"], requested_amount=float(r["requested_amount"]),
            desired_completion_date=dt.date.fromisoformat(r["desired_completion_date"])
            if r["desired_completion_date"].strip() else None,
            allows_partial_payment=r["allows_partial_payment"].strip().lower() == "true",
            request_text=r["request_text"],
        ))
    return out


def sample_dataset(ds: Dataset) -> Dataset:
    """A Dataset view whose `requests` are the 25 solved samples."""
    ds2 = Dataset(**{**ds.__dict__})
    ds2.requests = sample_requests(ds)
    return ds2


def check_gt(ds: Dataset) -> int:
    sds = sample_dataset(ds)
    errs = verify.verify_rows(sds, ds.samples, strict_order=False)
    if errs:
        print(f"ground truth FAILS our verifier ({len(errs)} issues) -- the verifier is wrong:")
        for e in errs:
            print("  ", e)
        return 1
    print(f"ground truth passes verify.py on all {len(ds.samples)} samples")
    return 0


def _close(a: str, b: str, tol: float) -> bool:
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a.strip() == b.strip()
    if x == y:
        return True
    denom = max(abs(y), 1e-9)
    return abs(x - y) / denom <= tol


def score(ds: Dataset, predictions: dict[str, dict], tol: float = 0.01) -> dict:
    stats = {f: 0 for f in FIELDS}
    stats["amount_within_tol"] = 0
    n = len(ds.samples)
    misses: list[str] = []
    for gt in ds.samples:
        rid = gt["request_id"]
        pred = predictions.get(rid)
        if pred is None:
            misses.append(f"{rid}: no prediction")
            continue
        for f in FIELDS:
            g, p = gt[f].strip(), str(pred.get(f, "")).strip()
            if f == "amount_safe_to_pay":
                if _close(p, g, 0.0):
                    stats[f] += 1
                if _close(p, g, tol):
                    stats["amount_within_tol"] += 1
                else:
                    misses.append(f"{rid}: amount {p} vs {g}")
            else:
                if g == p:
                    stats[f] += 1
                else:
                    misses.append(f"{rid}: {f}\n      got  {p}\n      want {g}")
    return {"n": n, "stats": stats, "misses": misses}


def report(res: dict, show_misses: bool = True) -> None:
    n = res["n"]
    print(f"\n=== sample score ({n} solved examples) ===")
    for k, v in res["stats"].items():
        bar = "#" * round(20 * v / n)
        print(f"  {k:<30} {v:>3}/{n}  {bar}")
    if show_misses and res["misses"]:
        print(f"\n--- {len(res['misses'])} misses ---")
        for m in res["misses"]:
            print("  ", m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-gt", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    ds = loaders.load()
    if a.check_gt:
        return check_gt(ds)
    import pipeline  # noqa: E402  (imported late: only needed for a real run)
    sds = sample_dataset(ds)
    rows = pipeline.run(sds, sds.requests)
    preds = {r["request_id"]: r for r in rows}
    errs = verify.verify_rows(sds, rows, strict_order=False)
    if errs:
        print(f"!! our own output fails verify.py ({len(errs)} issues)")
        for e in errs[:40]:
            print("  ", e)
    report(score(ds, preds), show_misses=not a.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
