"""Invariant checks for the pieces the sample scorer cannot exercise directly.

    python3 code/evaluation/selftest.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import evidence  # noqa: E402
import fmt       # noqa: E402
import loaders   # noqa: E402
import verify    # noqa: E402
from fx import FX          # noqa: E402
from ledger import Series  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def main() -> int:
    # --- formatting reproduces the solved samples byte-for-byte -------------
    check("money_plan int", fmt.money_plan(25256), "25256")
    check("money_plan 1dp", fmt.money_plan(996.6), "996.60")
    check("money_plan 2dp", fmt.money_plan(15952906.67), "15952906.67")
    check("money_field int", fmt.money_field(462.0), "462")
    check("money_field 1dp", fmt.money_field(17229139.2), "17229139.2")
    check("money_field 2dp", fmt.money_field(87170.56), "87170.56")

    # --- monthly series land on a calendar day, not every N days ------------
    s = Series(key="k", event_id="e", user_id="u", category="salary", description="d",
               direction="credit", amount=1.0, cadence_days=31,
               last_date=dt.date(2025, 4, 15), flexibility="fixed",
               minimum_allowed_amount=None, anchor_day=15)
    got = list(s.occurrences(dt.date(2025, 4, 16), dt.date(2025, 7, 31)))
    check("monthly anchor", got,
          [dt.date(2025, 5, 15), dt.date(2025, 6, 15), dt.date(2025, 7, 15)])

    # a 31st-anchored series must not be dragged back by a short month
    s2 = Series(key="k", event_id="e", user_id="u", category="rent", description="d",
                direction="debit", amount=1.0, cadence_days=30,
                last_date=dt.date(2025, 1, 31), flexibility="fixed",
                minimum_allowed_amount=None, anchor_day=31)
    got2 = list(s2.occurrences(dt.date(2025, 2, 1), dt.date(2025, 4, 30)))
    check("short-month clamp", got2,
          [dt.date(2025, 2, 28), dt.date(2025, 3, 31), dt.date(2025, 4, 30)])

    # weekly series still step by days
    s3 = Series(key="k", event_id="e", user_id="u", category="groceries", description="d",
                direction="debit", amount=1.0, cadence_days=7,
                last_date=dt.date(2025, 1, 1), flexibility="fixed",
                minimum_allowed_amount=None)
    check("weekly step", list(s3.occurrences(dt.date(2025, 1, 2), dt.date(2025, 1, 23))),
          [dt.date(2025, 1, 8), dt.date(2025, 1, 15), dt.date(2025, 1, 22)])

    # --- the grounding guard rejects ungrounded optimism --------------------
    text = "Your monthly salary has increased to IDR 42750000 from 2025-08-15."
    check("guard accepts grounded", evidence.grounded(
        {"kind": "salary_set_level", "amount": 42750000, "evidence_quote": "q"}, text), True)
    check("guard accepts separators", evidence.grounded(
        {"kind": "salary_set_level", "amount": 42750000, "evidence_quote": "q"},
        "salary is IDR 42,750,000"), True)
    check("guard rejects invented figure", evidence.grounded(
        {"kind": "salary_set_level", "amount": 99999999, "evidence_quote": "q"}, text), False)
    check("guard rejects missing quote", evidence.grounded(
        {"kind": "income_one_off", "amount": 42750000, "evidence_quote": ""}, text), False)
    check("guard rejects unquantified expense", evidence.grounded(
        {"kind": "new_recurring_expense", "amount": None, "evidence_quote": "q"},
        "a new recurring childcare payment begins"), False)

    # --- FX round-trips across the sparse dated rate graph ------------------
    ds = loaders.load()
    fx = FX(ds.rates)
    on = dt.date(2025, 6, 20)
    for a in ("INR", "ZAR", "IDR", "USD", "EUR"):
        for b in ("INR", "ZAR", "IDR", "USD", "EUR"):
            back = fx.convert(fx.convert(100.0, a, b, on), b, a, on)
            if abs(back - 100.0) > 1e-6:
                FAILS.append(f"fx round-trip {a}->{b}->{a} = {back}")

    # --- the verifier actually rejects contract violations -------------------
    good = {r["request_id"]: dict(r) for r in ds.samples}
    from score import sample_dataset  # noqa: E402
    sds = sample_dataset(ds)
    rows = [dict(r) for r in ds.samples]
    check("verifier passes ground truth", verify.verify_rows(sds, rows, strict_order=False), [])

    bad = [dict(r) for r in ds.samples]
    bad[0]["amount_safe_to_pay"] = str(float(bad[0]["requested_amount"]) * 2)
    if not verify.verify_rows(sds, bad, strict_order=False):
        FAILS.append("verifier missed amount_safe_to_pay above requested_amount")

    bad2 = [dict(r) for r in ds.samples]
    bad2[1]["payment_plan"] = "2099-01-01:1|2098-01-01:1"
    if not verify.verify_rows(sds, bad2, strict_order=False):
        FAILS.append("verifier missed a non-chronological payment_plan")

    bad3 = [dict(r) for r in ds.samples]
    bad3[2]["affordability_status"] = "affordable_now"
    if not verify.verify_rows(sds, bad3, strict_order=False):
        FAILS.append("verifier missed affordable_now with earliest != request_date")

    if FAILS:
        print(f"{len(FAILS)} FAILURES")
        for f in FAILS:
            print("  -", f)
        return 1
    print("selftest: all invariants hold")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
