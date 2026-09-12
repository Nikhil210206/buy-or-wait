"""Hard gate on the output contract.

This runs before `output.csv` is written. Any violation is a bug in the solver,
not a warning to be tolerated -- the submission checklist in the starter repo
turns each of these into a scoring failure.
"""
from __future__ import annotations

import datetime as dt
import re

from loaders import Dataset

COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]

STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}

# Which methods each status may carry. Derived from the spec and confirmed
# against all 25 solved samples by evaluation/score.py.
ALLOWED = {
    "affordable_now": {"full_payment"},
    "affordable_with_plan": {"full_payment", "partial_payment", "installments"},
    "affordable_later": {"wait"},
    "not_affordable": {"not_recommended"},
}

PAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}):(-?\d+(?:\.\d+)?)$")
CHANGE_RE = re.compile(r"^(?:stop:(\w+)|reduce_to:(\w+):(-?\d+(?:\.\d+)?))$")
EPS = 0.01


def parse_plan(s: str) -> list[tuple[dt.date, float]] | None:
    if s == "none":
        return []
    out = []
    for part in s.split("|"):
        m = PAY_RE.match(part)
        if not m:
            return None
        out.append((dt.date.fromisoformat(m.group(1)), float(m.group(2))))
    return out


def verify_rows(ds: Dataset, rows: list[dict], *, strict_order: bool = True) -> list[str]:
    errs: list[str] = []
    reqs = {r.request_id: r for r in ds.requests}

    if strict_order:
        got = [r["request_id"] for r in rows]
        want = [r.request_id for r in ds.requests]
        if got != want:
            errs.append(f"row set/order mismatch: {len(got)} rows vs {len(want)} requests")

    for row in rows:
        rid = row["request_id"]
        req = reqs.get(rid)
        if req is None:
            errs.append(f"{rid}: unknown request_id")
            continue
        prof = ds.profiles[req.user_id]
        E = lambda m: errs.append(f"{rid}: {m}")

        # --- amount_safe_to_pay -------------------------------------------
        try:
            safe = float(row["amount_safe_to_pay"])
        except ValueError:
            E(f"amount_safe_to_pay not numeric: {row['amount_safe_to_pay']!r}")
            continue
        if safe < -EPS or safe > req.requested_amount + EPS:
            E(f"amount_safe_to_pay {safe} outside [0, {req.requested_amount}]")

        # --- enums ---------------------------------------------------------
        status, method = row["affordability_status"], row["recommended_payment_method"]
        if status not in STATUSES:
            E(f"bad affordability_status {status!r}")
            continue
        if method not in METHODS:
            E(f"bad recommended_payment_method {method!r}")
            continue
        if method not in ALLOWED[status]:
            E(f"method {method!r} not allowed for status {status!r}")

        # --- earliest date --------------------------------------------------
        edate_s = row["earliest_date_for_full_payment"].strip()
        edate = dt.date.fromisoformat(edate_s) if edate_s else None
        if status == "affordable_now" and edate != req.request_date:
            E(f"affordable_now requires earliest == request_date, got {edate_s!r}")
        if edate and edate < req.request_date:
            E(f"earliest_date {edate} before request_date {req.request_date}")

        # --- payment_plan ----------------------------------------------------
        plan = parse_plan(row["payment_plan"])
        if plan is None:
            E(f"malformed payment_plan {row['payment_plan']!r}")
            continue
        if [d for d, _ in plan] != sorted(d for d, _ in plan):
            E("payment_plan not in chronological order")
        if method in ("not_recommended",) and plan:
            E("not_recommended must have payment_plan 'none'")
        if method in ("full_payment", "partial_payment", "installments", "wait") and not plan:
            E(f"{method} requires a non-empty payment_plan")

        if method == "installments":
            opts = ds.options_by_request.get(rid, [])
            if not any(_matches_option(plan, o) for o in opts if o.payment_method == "installments"):
                E(f"installment plan matches no supplied option: {row['payment_plan']}")
            if "installments" not in prof.payment_methods:
                E("installments not in payment_methods_user_will_consider")

        if method == "partial_payment":
            if not req.allows_partial_payment:
                E("partial_payment but request does not allow partial payment")
            if "partial_payment" not in prof.payment_methods:
                E("partial_payment not in payment_methods_user_will_consider")
            if len(plan) != 2:
                E(f"partial_payment needs exactly 2 payments, got {len(plan)}")
            else:
                if abs(sum(a for _, a in plan) - req.requested_amount) > EPS:
                    E(f"partial payments sum to {sum(a for _, a in plan)}, need {req.requested_amount}")
                if plan[0][0] != req.request_date:
                    E("first partial payment must fall on request_date")
                if abs(plan[0][1] - safe) > EPS:
                    E(f"first partial payment {plan[0][1]} != amount_safe_to_pay {safe}")
                if edate and plan[1][0] != edate:
                    E("second partial payment must fall on earliest_date_for_full_payment")
                if req.desired_completion_date and plan[1][0] > req.desired_completion_date:
                    E("second partial payment after desired_completion_date")
            if not (0 < safe < req.requested_amount):
                E(f"partial_payment requires 0 < amount_safe_to_pay < requested_amount (got {safe})")

        if method == "full_payment" and "full_payment" not in prof.payment_methods:
            E("full_payment not in payment_methods_user_will_consider")
        if method == "wait" and "full_payment" not in prof.payment_methods:
            E("wait implies full payment later, but user does not accept full_payment")

        # --- spending_changes_needed -------------------------------------------
        sc = row["spending_changes_needed"].strip()
        if sc != "none":
            parts = sc.split("|")
            if len(parts) > 3:
                E(f"{len(parts)} spending changes, max 3")
            touched: set[str] = set()
            for p in parts:
                m = CHANGE_RE.match(p)
                if not m:
                    E(f"malformed spending change {p!r}")
                    continue
                eid = m.group(1) or m.group(2)
                if eid in touched:
                    E(f"event {eid} targeted by more than one spending change")
                touched.add(eid)
                ev = ds.events_by_id.get(eid)
                if ev is None or ev.user_id != req.user_id:
                    E(f"spending change targets {eid}, not an event of {req.user_id}")
                    continue
                if not ev.is_flexible:
                    E(f"{eid} is {ev.flexibility}, not flexible")
                if ev.category in prof.protected_categories:
                    E(f"{eid} is in protected category {ev.category}")
                if m.group(1):  # stop:
                    if not ev.can_stop:
                        E(f"{eid} flexibility {ev.flexibility} does not allow stop")
                    if ev.category not in prof.stoppable_categories:
                        E(f"user will not stop category {ev.category}")
                else:            # reduce_to:
                    newamt = float(m.group(3))
                    if not ev.can_reduce:
                        E(f"{eid} flexibility {ev.flexibility} does not allow reduce")
                    if ev.category not in prof.reducible_categories:
                        E(f"user will not reduce category {ev.category}")
                    if ev.minimum_allowed_amount is not None and newamt < ev.minimum_allowed_amount - EPS:
                        E(f"reduce_to {newamt} below minimum_allowed_amount {ev.minimum_allowed_amount}")
                    if ev.amount is not None and newamt > ev.amount + EPS:
                        E(f"reduce_to {newamt} exceeds current amount {ev.amount}")

        if not row["decision_explanation"].strip():
            E("empty decision_explanation")

    return errs


def _matches_option(plan, opt) -> bool:
    if opt.number_of_payments != len(plan):
        return False
    freq = opt.payment_frequency_days or 0
    for k, (d, a) in enumerate(plan):
        if d != opt.first_payment_date + dt.timedelta(days=freq * k):
            return False
        if abs(a - opt.payment_amount) > EPS:
            return False
    return True
