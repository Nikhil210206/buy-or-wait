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

import datetime as dt
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from fx import FX
from loaders import Dataset, Event

HORIZON_DAYS = 90

# Categories whose spend is a rotating merchant pool rather than one contract.
POOLED_CATEGORIES = {"groceries", "transport", "dining", "shopping", "entertainment", "healthcare"}

DEAD_STATUSES = {"cancelled", "failed", "unrealized"}


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

    def occurrences(self, start: dt.date, end: dt.date):
        d = self.last_date + dt.timedelta(days=self.cadence_days)
        while d <= end:
            if d >= start:
                yield d
            d += dt.timedelta(days=self.cadence_days)


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
    # spending changes under evaluation
    stop_series: set[str] = field(default_factory=set)                # event_ids
    reduce_series: dict[str, float] = field(default_factory=dict)     # event_id -> new amount

    def copy(self) -> "Adjustments":
        return Adjustments(
            set(self.drop_events), dict(self.amend_amount), dict(self.delay_event),
            list(self.extra_flows), list(self.salary_level), self.salary_stop_from,
            self.salary_next_override, list(self.series_scale),
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
        return self.evidence_amounts.get(e.event_id)

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
            recent = [e for e in evs if (as_of - e.cash_date).days <= 120] or evs[-8:]
            amts = [self.home_amount(e) for e in recent]
            amts = [a for a in amts if a is not None]
            if not amts:
                continue
            last = max(recent, key=lambda e: e.cash_date)
            out.append(Series(
                key=f"{user_id}:{cat}:*pooled*", event_id=last.event_id, user_id=user_id,
                category=cat, description=f"{cat} spending", direction=dirn,
                amount=st.mean(amts), cadence_days=cad, last_date=dates[-1],
                flexibility=_pool_flexibility(recent),
                minimum_allowed_amount=_pool_min(recent), pooled=True,
            ))

        # (3) salary: anchor on the most recent confirmed or scheduled pay
        sal = [e for e in self.ds.events_by_user.get(user_id, [])
               if e.category == "salary" and e.direction == "credit"
               and e.status in ("settled", "scheduled") and self.raw_amount(e) is not None]
        sal.sort(key=lambda e: e.cash_date)
        if sal:
            dates = [e.cash_date for e in sal]
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            cad = round(st.median(gaps)) if gaps else 30
            if not (25 <= cad <= 35):
                cad = 30
            last = sal[-1]
            amt = self.home_amount(last)
            # A prorated/partial first payslip is not the recurring level.
            if len(sal) >= 2 and "prorat" in last.description.lower():
                amt = self.home_amount(sal[-2]) or amt
            if amt is not None:
                out.append(Series(
                    key=f"{user_id}:salary", event_id=last.event_id, user_id=user_id,
                    category="salary", description=last.description, direction="credit",
                    amount=amt, cadence_days=cad, last_date=last.cash_date,
                    flexibility="fixed", minimum_allowed_amount=None,
                ))

        self._series_cache[ck] = out
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
            if e.category == "salary" and adj.salary_next_override is not None:
                amt = adj.salary_next_override
            if e.category == "salary" and adj.salary_stop_from and when >= adj.salary_stop_from:
                continue
            flows.append(Flow(when, amt if e.direction == "credit" else -amt,
                              "known", e.event_id, e.category))

        for s in self.series_for(user_id, as_of):
            if s.event_id in adj.stop_series:
                continue
            amt = adj.reduce_series.get(s.event_id, s.amount)
            for d in s.occurrences(as_of + dt.timedelta(days=1), end):
                a = amt
                for cat, factor, eff in adj.series_scale:
                    if cat == s.category and (eff is None or d >= eff):
                        a *= factor
                if s.category == "salary":
                    if adj.salary_stop_from and d >= adj.salary_stop_from:
                        continue
                    for eff, lvl in adj.salary_level:
                        if d >= eff:
                            a = lvl
                flows.append(Flow(d, a if s.direction == "credit" else -a,
                                  "recurring", s.event_id, s.category))

        flows.extend(f for f in adj.extra_flows if as_of < f.date <= end)
        flows.sort(key=lambda f: (f.date, f.ref))
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
