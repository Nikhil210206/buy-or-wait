"""decision_explanation text.

The solved samples are visibly generated from a small template set, so we
reproduce that register rather than inventing prose: the explanation states the
recommended action and the one financial fact behind it (the minimum balance the
plan protects). Everything interpolated here is a number that already appears in
the plan, so an explanation cannot assert anything the recommendation does not.
"""
from __future__ import annotations

import datetime as dt

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def amt(cur: str, v: float) -> str:
    s = f"{v:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return f"{cur} {s}"


def longdate(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month]} {d.year}"


def _changes_sentence(cur: str, changes) -> str:
    parts = []
    for i, c in enumerate(changes):
        what = f"the {c.description.lower()}"
        if c.kind == "stop":
            verb = "Stop" if i == 0 else "stop"
            parts.append(f"{verb} {what}")
        else:
            verb = "Reduce" if i == 0 else "reduce"
            parts.append(f"{verb} {what} to {amt(cur, c.new_amount)}")
    if len(parts) == 1:
        return parts[0]
    return " and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 2 else " and ".join(parts)


def explain(ds, req, row, best, changes) -> str:
    prof = ds.profiles[req.user_id]
    cur = prof.home_currency
    floor = amt(cur, prof.minimum_balance_to_keep)
    method = row["recommended_payment_method"]

    if method == "full_payment":
        total = amt(cur, best.payments[0][1])
        if changes:
            return (f"{_changes_sentence(cur, changes)}, then pay {total} today. "
                    f"This leaves at least {floor} available.")
        return (f"Pay {total} today. "
                f"This leaves at least {floor} available over the next 90 days.")

    if method == "installments":
        n = len(best.payments)
        per = amt(cur, best.payments[0][1])
        return (f"Use {n} installments of {per}, starting {longdate(best.start)}. "
                f"This leaves at least {floor} available.")

    if method == "partial_payment":
        first = amt(cur, best.payments[0][1])
        rest = amt(cur, best.payments[1][1])
        return (f"Pay {first} today and the remaining {rest} on {longdate(best.payments[1][0])}. "
                f"This completes the full request and keeps the {floor} minimum protected.")

    if method == "wait":
        return (f"Pay {amt(cur, req.requested_amount)} in full on {longdate(best.start)}. "
                f"Paying earlier would take the balance below the {floor} minimum.")

    # not_recommended
    safe = float(row["amount_safe_to_pay"])
    only_partial = prof.payment_methods == ["partial_payment"] and req.allows_partial_payment
    if safe > 0 and only_partial:
        return (f"Do not proceed with the {amt(cur, req.requested_amount)} request. "
                f"Although {amt(cur, safe)} is available today, the full amount cannot be "
                f"completed safely within 90 days.")
    when = longdate(req.desired_completion_date) if req.desired_completion_date else "the deadline"
    return (f"Do not make this payment by {when}. "
            f"None of the available options keeps the {floor} minimum protected.")
