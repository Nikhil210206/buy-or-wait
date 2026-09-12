"""Orchestrator: dataset + requests -> output rows."""
from __future__ import annotations

from loaders import Dataset, Request
from verify import COLUMNS


def run(ds: Dataset, requests: list[Request]) -> list[dict]:
    from ledger import Ledger
    from solver import solve

    led = Ledger(ds)
    return [solve(ds, led, req) for req in requests]


def baseline(ds: Dataset, requests: list[Request]) -> list[dict]:
    """Schema-valid fallback so a submittable output.csv always exists."""
    return [{
        "request_id": r.request_id,
        "amount_safe_to_pay": "0",
        "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended",
        "payment_plan": "none",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "decision_explanation": "Placeholder row; solver has not run for this request.",
    } for r in requests]


def write_csv(path, rows: list[dict]) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
