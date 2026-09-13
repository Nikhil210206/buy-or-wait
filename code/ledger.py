"""Financial-state reconstruction and the 90-day forecast.

Two kinds of cash flow feed the forecast:

* **known**     -- supplied event rows whose money moves after `request_date`
                   (pending debits reserved, scheduled credits counted on their
                   settlement date, pending credits ignored until they settle).
* **recurring** -- series inferred from settled history, because the supplied
                   rows stop at/near the request date but commitments continue.

Recurrence is detected in two regimes, which is what the data actually looks
like: contractual items (rent, utilities, loan instalments, subscriptions,
salary) repeat monthly under a stable `description`, while essential variable
spend (groceries, transport, dining) is a rotating pool of merchant names drawn
at a weekly or fortnightly cadence within a `category`.
"""
from __future__ import annotations

import calendar
import datetime as dt
import os
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from fx import FX
from loaders import Dataset, Event

HORIZON_DAYS = 90

# Categories whose spend is a rotating merchant pool rather than one contract.
POOLED_CATEGORIES = {"groceries", "transport", "dining", "shopping", "entertainment", "healthcare"}

DEAD_STATUSES = {"cancelled", "failed", "unrealized"}

# AGENTS.md: "Forecast essential variable spending conservatively." How much
# conservatism is a calibration choice, so it is configurable and selected by
# evaluation/calibrate.py against the solved samples rather than guessed.
#   BOW_POOL_MODE  occurrence = per-occurrence mean x cadence
#                  rate       = observed daily burn x cadence (robust to
#                               cadence-estimation error)
#   BOW_POOL_MULT  safety multiplier on the projected variable spend
# Defaults below were selected against the 25 solved samples: per-occurrence
# mean over a 180-day history, with no safety margin. An earlier sweep chose a
# 1.05 margin, but that was compensating for monthly series drifting by a fixed
# 31-day step; once they were projected on calendar months the margin stopped
# helping and now costs accuracy. Two global hyperparameters, no per-request or
# per-user fitting.
POOL_MODE = os.environ.get("BOW_POOL_MODE", "occurrence")
POOL_MULT = float(os.environ.get("BOW_POOL_MULT", "1.0"))
POOL_WINDOW = int(os.environ.get("BOW_POOL_WINDOW", "180"))


def _next_month(base: dt.date, anchor_day: int) -> dt.date:
    """Same day next month, clamped to the month's length.

    The anchor is carried separately so a short month does not permanently
    shift the series (31 Jan -> 28 Feb -> 31 Mar, not -> 28 Mar).
    """
    year, month = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
    return dt.date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


@dataclass
class Series:
    """A repeating cash flow projected forward from history."""
    key: str
    event_id: str            # most recent occurrence -- what spending changes target
    user_id: str
    category: str
    description: str
    direction: str
    amount: float            # home currency, per occurrence
    cadence_days: int
    last_date: dt.date
    flexibility: str
    minimum_allowed_amount: float | None
    pooled: bool = False
    stable: bool = True      # amounts barely vary -> contractual base pay
    anchor_day: int = 0      # modal day-of-month for monthly series

    def occurrences(self, start: dt.date, end: dt.date):
        # A monthly commitment lands on the same calendar day each month, not
        # every N days. Stepping by a median gap of 31 makes salary drift
        # 15th -> 16th -> 17th across the forecast, which throws out both the
        # balance path and earliest_date_for_full_payment.
        monthly = 26 <= self.cadence_days <= 32
        anchor = self.anchor_day or self.last_date.day
        d = _next_month(self.last_date, anchor) if monthly \
            else self.last_date + dt.timedelta(days=self.cadence_days)
        while d <= end:
            if d >= start:
                yield d
            d = _next_month(d, anchor) if monthly \
                else d + dt.timedelta(days=self.cadence_days)


@dataclass
class Flow:
    date: dt.date
    amount: float            # signed, home currency
    kind: str                # known | recurring
    ref: str                 # event_id or series key
    category: str = ""


@dataclass
class Adjustments:
    """Evidence-derived changes applied on top of the raw history.

    Populated by the AI evidence layer (see evidence.py); empty by default so
    the deterministic core runs standalone.
    """
    drop_events: set[str] = field(default_factory=set)
    amend_amount: dict[str, float] = field(default_factory=dict)      # event_id -> home-currency amount
    delay_event: dict[str, dt.date] = field(default_factory=dict)
    extra_flows: list[Flow] = field(default_factory=list)
    salary_level: list[tuple[dt.date, float]] = field(default_factory=list)   # (effective, new per-period amount)
    salary_stop_from: dt.date | None = None
    salary_next_override: float | None = None                         # one-off change to the next salary
    series_scale: list[tuple[str, float, dt.date | None]] = field(default_factory=list)  # (category, factor, effective)
    salary_primary_level: tuple[dt.date | None, float] | None = None   # confirmed base pay
    salary_only_primary: bool = False      # drop unconfirmed commission/gig streams
    drop_unstable_income: bool = False     # pending gig/platform payouts are not money yet
    new_recurring: list[tuple[str, float, dt.date, int]] = field(default_factory=list)  # (category, amount, from, cadence)
    # spending changes under evaluation
    stop_series: set[str] = field(default_factory=set)                # event_ids
    reduce_series: dict[str, float] = field(default_factory=dict)     # event_id -> new amount

    def copy(self) -> "Adjustments":
        return Adjustments(
            set(self.drop_events), dict(self.amend_amount), dict(self.delay_event),
            list(self.extra_flows), list(self.salary_level), self.salary_stop_from,
            self.salary_next_override, list(self.series_scale),
            self.salary_primary_level, self.salary_only_primary, self.drop_unstable_income,
            list(self.new_recurring),
            set(self.stop_series), dict(self.reduce_series),
        )


class Ledger:
    def __init__(self, ds: Dataset, evidence_amounts: dict[str, float] | None = None):
        self.ds = ds
        self.fx = FX(ds.rates)
        # event_id -> amount in the event's OWN currency, recovered from an image
        self.evidence_amounts = evidence_amounts or {}
        self._series_cache: dict[tuple[str, dt.date], list[Series]] = {}

    # ---- amounts -----------------------------------------------------------

    def raw_amount(self, e: Event) -> float | None:
        if e.amount is not None:
            return e.amount
        got = self.evidence_amounts.get(e.event_id)
        if got is not None:
            return got
        # "Do not treat a blank amount as zero." If the image pass could not
        # recover a figure, fall back to the user's own typical spend in that
        # category rather than silently dropping the row.
        return self._peer_estimate(e)

    def _peer_estimate(self, e: Event) -> float | None:
        peers = [x.amount for x in self.ds.events_by_user.get(e.user_id, [])
                 if x.category == e.category and x.currency == e.currency
                 and x.amount is not None and x.direction == e.direction]
        return st.median(peers) if peers else None

    def home_amount(self, e: Event, adj: Adjustments | None = None) -> float | None:
        if adj and e.event_id in adj.amend_amount:
            return adj.amend_amount[e.event_id]
        a = self.raw_amount(e)
        if a is None:
            return None
        home = self.ds.profiles[e.user_id].home_currency
        return self.fx.convert(a, e.currency, home, e.cash_date)

    # ---- which rows move cash ----------------------------------------------

    def is_duplicate_charge(self, e: Event) -> bool:
        """A pending debit linked to an already-settled parent of the same amount."""
        if e.status != "pending" or e.direction != "debit" or not e.linked_event_id:
            return False
        p = self.ds.events_by_id.get(e.linked_event_id)
        return bool(p and p.status == "settled" and p.direction == "debit"
                    and p.amount is not None and e.amount is not None
                    and abs(p.amount - e.amount) < 1e-6)

    def counts_as_cash(self, e: Event) -> bool:
        if e.status in DEAD_STATUSES or e.direction == "non_cash":
            return False
        # Pending credits (refunds, bonuses, prize money, payouts) are not money yet.
        if e.status == "pending" and e.direction == "credit":
            return False
        if self.is_duplicate_charge(e):
            return False
        return True

    # ---- recurrence detection ------------------------------------------------

    def series_for(self, user_id: str, as_of: dt.date) -> list[Series]:
        ck = (user_id, as_of)
        if ck in self._series_cache:
            return self._series_cache[ck]

        prof = self.ds.profiles[user_id]
        hist = [e for e in self.ds.events_by_user.get(user_id, [])
                if e.status == "settled" and e.cash_date <= as_of
                and e.direction in ("debit", "credit") and self.raw_amount(e) is not None]

        out: list[Series] = []
        claimed: set[str] = set()

        # (1) contractual: stable description repeating on a monthly-ish cadence
        groups: dict[tuple[str, str, str], list[Event]] = defaultdict(list)
        for e in hist:
            if e.category == "salary":
                continue
            groups[(e.description, e.category, e.direction)].append(e)

        for (desc, cat, dirn), evs in groups.items():
            evs.sort(key=lambda e: e.cash_date)
            dates = [e.cash_date for e in evs]
            if len(dates) < 3:
                continue
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            cad = round(st.median(gaps))
            if not (25 <= cad <= 35):
                continue
            # A contract repeats on a tight cycle. Anything looser is a rotating
            # merchant that merely averaged out to ~monthly (e.g. a commuter pass
            # bought at 28/28/70/42-day gaps), and belongs to the pooled regime.
            if any(abs(g - cad) > 5 for g in gaps):
                continue
            last = evs[-1]
            amt = self.home_amount(last)
            if amt is None:
                continue
            out.append(Series(
                key=f"{user_id}:{cat}:{desc}", event_id=last.event_id, user_id=user_id,
                category=cat, description=desc, direction=dirn, amount=amt,
                cadence_days=cad, last_date=last.cash_date, flexibility=last.flexibility,
                minimum_allowed_amount=last.minimum_allowed_amount,
                anchor_day=Counter(d.day for d in dates).most_common(1)[0][0],
            ))
            claimed.update(e.event_id for e in evs)

        # (2) pooled essentials: rotating merchants inside one category
        by_cat: dict[tuple[str, str], list[Event]] = defaultdict(list)
        for e in hist:
            if e.event_id in claimed or e.category == "salary":
                continue
            if e.category not in POOLED_CATEGORIES:
                continue
            by_cat[(e.category, e.direction)].append(e)

        for (cat, dirn), evs in by_cat.items():
            evs.sort(key=lambda e: e.cash_date)
            dates = sorted({e.cash_date for e in evs})
            span = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
            if len(dates) < 5 or span < 60:
                continue
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            cad = round(st.median(gaps))
            if not (1 <= cad <= 21):
                continue
            recent = [e for e in evs if (as_of - e.cash_date).days <= POOL_WINDOW] or evs[-8:]
            amts = [self.home_amount(e) for e in recent]
            amts = [a for a in amts if a is not None]
            if not amts:
                continue
            last = max(recent, key=lambda e: e.cash_date)
            if POOL_MODE == "rate":
                first = min(e.cash_date for e in recent)
                days = max((last.cash_date - first).days, 1)
                per_occurrence = sum(amts) / days * cad
            else:
                per_occurrence = st.mean(amts)
            per_occurrence *= POOL_MULT
            out.append(Series(
                key=f"{user_id}:{cat}:*pooled*", event_id=last.event_id, user_id=user_id,
                category=cat, description=f"{cat} spending", direction=dirn,
                amount=per_occurrence, cadence_days=cad, last_date=dates[-1],
                flexibility=_pool_flexibility(recent),
                minimum_allowed_amount=_pool_min(recent), pooled=True,
            ))

        # (3) income: one series per pay stream.
        #
        # Users can have several concurrent streams (e.g. a base salary on the
        # 15th plus a commission on the 24th), and a stream is sometimes renamed
        # mid-history ("Performance commission" -> "Monthly sales commission").
        # Clustering by day-of-month separates concurrent streams and survives
        # renames, which grouping by description does not.
        out.extend(self._income_series(user_id, as_of))

        self._series_cache[ck] = out
        return out


    # Descriptions that mark the end of a pay stream: the last occurrence is
    # terminal and nothing should be projected after it.
    TERMINAL_INCOME = ("final ", "previous employer", "last payroll")
    # Descriptions that are not a recurring pay level even when they land in the
    # stream: prorated stubs, bonuses and back-pay.
    ONE_OFF_INCOME = ("prorat", "bonus", "arrears", "one-time", "windfall")

    def _income_series(self, user_id: str, as_of: dt.date) -> list[Series]:
        evs = [e for e in self.ds.events_by_user.get(user_id, [])
               if e.category == "salary" and e.direction == "credit"
               and e.status in ("settled", "scheduled") and self.raw_amount(e) is not None]
        if not evs:
            return []
        evs.sort(key=lambda e: e.cash_date)

        # cluster by day-of-month (tolerance 3 days, wrapping at month end)
        clusters: list[list[Event]] = []
        for e in evs:
            day = e.cash_date.day
            for c in clusters:
                ref = c[-1].cash_date.day
                if min(abs(day - ref), 31 - abs(day - ref)) <= 3:
                    c.append(e)
                    break
            else:
                clusters.append([e])

        out: list[Series] = []
        for c in clusters:
            last = c[-1]
            desc = last.description.lower()
            if any(t in desc for t in self.TERMINAL_INCOME):
                continue                      # employment ended; project nothing
            if len(c) < 2 and not (last.status == "scheduled" or "confirmed" in desc):
                continue
            # the recurring level is the latest occurrence that is not a stub
            level_ev = next((e for e in reversed(c)
                             if not any(t in e.description.lower() for t in self.ONE_OFF_INCOME)), last)
            amt = self.home_amount(level_ev)
            if amt is None:
                continue
            dates = [e.cash_date for e in c]
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            cad = round(st.median(gaps)) if gaps else 30
            if not (25 <= cad <= 35):
                cad = 30
            amounts = [self.home_amount(e) for e in c]
            amounts = [a for a in amounts if a is not None]
            spread = (st.pstdev(amounts) / st.mean(amounts)) if len(amounts) > 1 and st.mean(amounts) else 0.0
            out.append(Series(
                key=f"{user_id}:salary:{last.cash_date.day}", event_id=last.event_id,
                user_id=user_id, category="salary", description=last.description,
                direction="credit", amount=amt, cadence_days=cad, last_date=last.cash_date,
                flexibility="fixed", minimum_allowed_amount=None, stable=spread < 0.02,
                anchor_day=Counter(e.cash_date.day for e in c).most_common(1)[0][0],
            ))
        return out

    # ---- projection ------------------------------------------------------------

    def flows(self, user_id: str, as_of: dt.date, adj: Adjustments | None = None,
              horizon: int = HORIZON_DAYS) -> list[Flow]:
        adj = adj or Adjustments()
        end = as_of + dt.timedelta(days=horizon)
        flows: list[Flow] = []

        for e in self.ds.events_by_user.get(user_id, []):
            if e.event_id in adj.drop_events or not self.counts_as_cash(e):
                continue
            when = adj.delay_event.get(e.event_id, e.cash_date)
            if not (as_of < when <= end):
                continue
            amt = self.home_amount(e, adj)
            if amt is None:
                continue
            if e.category == "salary" and adj.salary_stop_from and when >= adj.salary_stop_from:
                continue
            flows.append(Flow(when, amt if e.direction == "credit" else -amt,
                              "known", e.event_id, e.category))

        series = self.series_for(user_id, as_of)
        primary = _primary_salary(series)

        for s in series:
            if s.event_id in adj.stop_series:
                continue
            if s.category == "salary" and adj.salary_only_primary and s is not primary:
                continue          # commission / gig income the employer has not confirmed
            if s.category == "salary" and adj.drop_unstable_income and not s.stable:
                continue          # a payout that is still pending is not money yet
            amt = adj.reduce_series.get(s.event_id, s.amount)
            for d in s.occurrences(as_of + dt.timedelta(days=1), end):
                a = amt
                for cat, factor, eff in adj.series_scale:
                    if cat == s.category and (eff is None or d >= eff):
                        a *= factor
                if s.category == "salary":
                    if adj.salary_stop_from and d >= adj.salary_stop_from:
                        continue
                    if adj.salary_primary_level and s is primary:
                        eff, lvl = adj.salary_primary_level
                        if eff is None or d >= eff:
                            a = lvl
                    for eff, lvl in adj.salary_level:
                        if d >= eff:
                            a = lvl
                flows.append(Flow(d, a if s.direction == "credit" else -a,
                                  "recurring", s.event_id, s.category))

        for cat, amount, start, cadence in adj.new_recurring:
            d = max(start, as_of + dt.timedelta(days=1))
            while d <= end:
                flows.append(Flow(d, -amount, "recurring", f"msg:{cat}", cat))
                d += dt.timedelta(days=cadence)

        flows.extend(f for f in adj.extra_flows if as_of < f.date <= end)
        flows.sort(key=lambda f: (f.date, f.ref))

        # A one-off change to the *next* payslip touches only the first pay event.
        if adj.salary_next_override is not None:
            for i, f in enumerate(flows):
                if f.category == "salary" and f.amount > 0:
                    flows[i] = Flow(f.date, adj.salary_next_override, f.kind, f.ref, f.category)
                    break
        return flows

    def balance_path(self, user_id: str, as_of: dt.date, adj: Adjustments | None = None,
                     extra: list[tuple[dt.date, float]] | None = None,
                     horizon: int = HORIZON_DAYS) -> list[tuple[dt.date, float]]:
        """Running balance after each dated cash movement, starting at the profile balance."""
        prof = self.ds.profiles[user_id]
        events: list[tuple[dt.date, float]] = [(f.date, f.amount) for f in
                                               self.flows(user_id, as_of, adj, horizon)]
        if extra:
            events.extend(extra)
        events.sort(key=lambda x: x[0])
        bal = prof.current_available_balance
        path = [(as_of, bal)]
        for d, a in events:
            bal += a
            path.append((d, bal))
        return path

    def min_balance(self, user_id: str, as_of: dt.date, adj: Adjustments | None = None,
                    extra: list[tuple[dt.date, float]] | None = None,
                    horizon: int = HORIZON_DAYS) -> float:
        return min(b for _, b in self.balance_path(user_id, as_of, adj, extra, horizon))


def _pool_flexibility(evs: list[Event]) -> str:
    c = Counter(e.flexibility for e in evs)
    for f in ("reducible_or_stoppable", "reducible", "stoppable"):
        if c.get(f):
            return f
    return "fixed"


def _pool_min(evs: list[Event]) -> float | None:
    vals = [e.minimum_allowed_amount for e in evs if e.minimum_allowed_amount is not None]
    return st.mean(vals) if vals else None


def _primary_salary(series: list[Series]) -> Series | None:
    """The confirmed base pay stream: prefer constant amounts, then the largest."""
    sal = [s for s in series if s.category == "salary"]
    if not sal:
        return None
    return max(sal, key=lambda s: (s.stable, s.amount))
