"""Plan enumeration, safety checking and ranking."""
from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field

from explain import explain
from fmt import money_field, money_plan, plan_str
from ledger import Adjustments, HORIZON_DAYS, Ledger, Series
from loaders import Dataset, PaymentOption, Request

EPS = 1e-6


@dataclass(frozen=True)
class Change:
    event_id: str
    kind: str          # stop | reduce_to
    new_amount: float | None
    category: str
    description: str

    def render(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{money_plan(self.new_amount)}"


@dataclass
class Candidate:
    method: str
    payments: list[tuple[dt.date, float]]
    total_paid: float
    changes: tuple[Change, ...] = ()
    option: PaymentOption | None = None

    @property
    def start(self) -> dt.date:
        return self.payments[0][0]

    @property
    def end(self) -> dt.date:
        return self.payments[-1][0]


class Timeline:
    """End-of-day balances over the forecast window, with prefix/suffix minima."""

    def __init__(self, led: Ledger, user_id: str, as_of: dt.date, adj: Adjustments):
        prof = led.ds.profiles[user_id]
        self.start = as_of
        self.end = as_of + dt.timedelta(days=HORIZON_DAYS)
        self.floor = prof.minimum_balance_to_keep

        daily: dict[dt.date, float] = {}
        for f in led.flows(user_id, as_of, adj):
            daily[f.date] = daily.get(f.date, 0.0) + f.amount

        self.days = [as_of] + sorted(daily)
        bal = prof.current_available_balance
        self.bal = [bal]
        for d in self.days[1:]:
            bal += daily[d]
            self.bal.append(bal)

        n = len(self.bal)
        self.pre = [0.0] * n     # min of bal[0..i]
        self.suf = [0.0] * n     # min of bal[i..n-1]
        run = float("inf")
        for i in range(n):
            run = min(run, self.bal[i])
            self.pre[i] = run
        run = float("inf")
        for i in range(n - 1, -1, -1):
            run = min(run, self.bal[i])
            self.suf[i] = run

    def _idx_from(self, d: dt.date) -> int:
        """First index whose day is >= d."""
        lo, hi = 0, len(self.days)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.days[mid] < d:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def min_balance(self) -> float:
        return self.suf[0]

    def safe_today(self, amount: float) -> bool:
        return self.suf[0] - amount >= self.floor - EPS

    def max_payable_today(self) -> float:
        return max(0.0, self.suf[0] - self.floor)

    def safe_single(self, d: dt.date, amount: float) -> bool:
        """Paying `amount` on day d, with nothing else changed."""
        if d < self.start or d > self.end:
            return False
        i = self._idx_from(d)
        if i > 0 and self.pre[i - 1] < self.floor - EPS:
            return False
        if i >= len(self.bal):
            return True
        return self.suf[i] - amount >= self.floor - EPS

    def safe_schedule(self, payments: list[tuple[dt.date, float]]) -> bool:
        """General case: re-run the window with the payments applied."""
        if any(d > self.end for d, _ in payments):
            return False
        extra: dict[dt.date, float] = {}
        for d, a in payments:
            extra[d] = extra.get(d, 0.0) + a
        merged = sorted(set(self.days) | set(extra))
        bal = self.bal[0]
        i = 0
        cum = 0.0
        for d in merged:
            while i + 1 < len(self.days) and self.days[i + 1] <= d:
                i += 1
                cum = self.bal[i] - self.bal[0]
            paid = sum(a for dd, a in extra.items() if dd <= d)
            if self.bal[0] + cum - paid < self.floor - EPS:
                return False
        return True

    def earliest_full(self, amount: float, until: dt.date | None = None) -> dt.date | None:
        limit = min(self.end, until) if until else self.end
        d = self.start
        while d <= limit:
            if self.safe_single(d, amount):
                return d
            d += dt.timedelta(days=1)
        return None


def _eligible_changes(ds: Dataset, led: Ledger, req: Request) -> list[Change]:
    prof = ds.profiles[req.user_id]
    out: list[Change] = []
    for s in led.series_for(req.user_id, req.request_date):
        ev = ds.events_by_id.get(s.event_id)
        if ev is None or not ev.is_flexible or ev.category in prof.protected_categories:
            continue
        # Reducing is less disruptive than stopping, so it is offered first and
        # _change_sets will try it first. The solved samples back this up: where a
        # subscription is both reducible and stoppable, the official answer reduces
        # it rather than stopping it.
        if (ev.can_reduce and ev.category in prof.reducible_categories
                and ev.minimum_allowed_amount is not None
                and ev.amount is not None and ev.minimum_allowed_amount < ev.amount):
            out.append(Change(ev.event_id, "reduce_to", ev.minimum_allowed_amount,
                              ev.category, ev.description))
        if ev.can_stop and ev.category in prof.stoppable_categories:
            out.append(Change(ev.event_id, "stop", None, ev.category, ev.description))
    return out


def _change_sets(changes: list[Change], max_n: int = 3):
    """Subsets touching each event at most once, smallest first."""
    by_event: dict[str, list[Change]] = {}
    for c in changes:
        by_event.setdefault(c.event_id, []).append(c)
    events = list(by_event)
    for n in range(1, min(max_n, len(events)) + 1):
        for combo in itertools.combinations(events, n):
            for picks in itertools.product(*(by_event[e] for e in combo)):
                yield tuple(picks)


def _apply(adj: Adjustments, changes: tuple[Change, ...]) -> Adjustments:
    a = adj.copy()
    for c in changes:
        if c.kind == "stop":
            a.stop_series.add(c.event_id)
        else:
            a.reduce_series[c.event_id] = c.new_amount
    return a


def _installment_payments(o: PaymentOption) -> list[tuple[dt.date, float]]:
    freq = o.payment_frequency_days or 0
    return [(o.first_payment_date + dt.timedelta(days=freq * k), o.payment_amount)
            for k in range(o.number_of_payments)]


def _rank_key(c: Candidate, req: Request):
    completes = (req.desired_completion_date is None or c.end <= req.desired_completion_date)
    oid = int(c.option.payment_option_id.split("_")[-1]) if c.option else 10**9
    return (0 if completes else 1, len(c.changes), round(c.total_paid, 2),
            c.start, len(c.payments), oid)


def solve(ds: Dataset, led: Ledger, req: Request, base_adj: Adjustments | None = None) -> dict:
    prof = ds.profiles[req.user_id]
    base = base_adj.copy() if base_adj else Adjustments()
    tl = Timeline(led, req.user_id, req.request_date, base)

    safe_today = min(req.requested_amount, tl.max_payable_today())
    earliest = tl.earliest_full(req.requested_amount)

    options = ds.options_by_request.get(req.request_id, [])
    full_opt = next((o for o in options if o.payment_method == "full_payment"), None)
    inst_opts = [o for o in options if o.payment_method == "installments"]
    if prof.max_installment_months is not None:
        inst_opts = [o for o in inst_opts if o.number_of_payments <= prof.max_installment_months]
    else:
        inst_opts = []

    eligible = _eligible_changes(ds, led, req)
    candidates: list[Candidate] = []

    def consider(method: str, payments: list[tuple[dt.date, float]], total: float,
                 option: PaymentOption | None, *, allow_changes: bool = True) -> None:
        # "The plan must complete the request by desired_completion_date." This is
        # a hard requirement, not a preference: no official sample answer contains
        # a plan whose last payment falls after the deadline.
        if req.desired_completion_date and payments and payments[-1][0] > req.desired_completion_date:
            return
        if tl.safe_schedule(payments):
            candidates.append(Candidate(method, payments, total, (), option))
            return
        if not allow_changes or not eligible:
            return
        for combo in _change_sets(eligible):
            tl2 = Timeline(led, req.user_id, req.request_date, _apply(base, combo))
            if tl2.safe_schedule(payments):
                candidates.append(Candidate(method, payments, total, combo, option))
                return   # smallest viable change set wins for this base plan

    # full payment today
    if "full_payment" in prof.payment_methods and full_opt is not None:
        consider("full_payment", [(full_opt.first_payment_date, full_opt.payment_amount)],
                 full_opt.total_payable_amount, full_opt)

    # installments
    if "installments" in prof.payment_methods:
        for o in inst_opts:
            consider("installments", _installment_payments(o), o.total_payable_amount, o)

    # partial payment: pay what is safe today, the rest on the earliest safe date
    if ("partial_payment" in prof.payment_methods and req.allows_partial_payment
            and earliest is not None and earliest > req.request_date
            and 0 < safe_today < req.requested_amount
            and (req.desired_completion_date is None or earliest <= req.desired_completion_date)):
        rest = req.requested_amount - safe_today
        consider("partial_payment", [(req.request_date, safe_today), (earliest, rest)],
                 req.requested_amount, None, allow_changes=False)

    # wait for the full amount
    if ("full_payment" in prof.payment_methods and earliest is not None
            and earliest > req.request_date):
        consider("wait", [(earliest, req.requested_amount)], req.requested_amount, None,
                 allow_changes=False)

    if candidates:
        best = min(candidates, key=lambda c: _rank_key(c, req))
        if best.method == "full_payment" and not best.changes:
            status = "affordable_now"
        elif best.method == "wait":
            status = "affordable_later"
        else:
            status = "affordable_with_plan"
        payments = best.payments
        changes = best.changes
    else:
        best = None
        status = "not_affordable"
        payments = []
        changes = ()

    method = best.method if best else "not_recommended"

    # `affordable_now` is defined as the full amount being safe on request_date.
    if status == "affordable_now":
        earliest = req.request_date

    row = {
        "request_id": req.request_id,
        "amount_safe_to_pay": money_field(safe_today),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_str(payments),
        "earliest_date_for_full_payment": earliest.isoformat() if earliest else "",
        "spending_changes_needed": "|".join(c.render() for c in changes) if changes else "none",
    }
    row["decision_explanation"] = explain(ds, req, row, best, changes)
    return row
