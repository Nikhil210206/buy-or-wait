"""Orchestrator: dataset + requests -> output rows."""
from __future__ import annotations

import csv

from loaders import Dataset, Request
from verify import COLUMNS


def run(ds: Dataset, requests: list[Request], *, provider: str = "gemini",
        use_evidence: bool = True) -> list[dict]:
    import evidence as ev_mod
    from ledger import Ledger
    from solver import solve

    ev = ev_mod.load(ds, provider) if use_evidence else None
    led = Ledger(ds, evidence_amounts=ev.image_amounts() if ev else None)

    rows = []
    for req in requests:
        adj = ev.adjustments_for(led, req.user_id, req.request_date) if ev else None
        rows.append(solve(ds, led, req, adj))
    return rows


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
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
