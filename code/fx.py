"""Dated currency conversion.

`exchange_rates.csv` only supplies a sparse set of directed pairs (EUR->ZAR,
USD->EUR, USD->IDR, USD->INR, EUR->USD) on monthly rate dates. Conversion
therefore needs inversion and triangulation through USD/EUR, which we do with a
BFS over the per-date rate graph. Per the dataset contract, a cash event is
converted using the rate row for its *settlement* date; we take the most recent
rate date on or before it (falling back to the earliest available).
"""
from __future__ import annotations

import datetime as dt
from collections import deque
from functools import lru_cache


class FX:
    def __init__(self, rates: list[tuple[dt.date, str, str, float]]):
        self.by_date: dict[dt.date, dict[str, dict[str, float]]] = {}
        for d, f, t, r in rates:
            g = self.by_date.setdefault(d, {})
            g.setdefault(f, {})[t] = r
            g.setdefault(t, {})[f] = 1.0 / r
        self.dates = sorted(self.by_date)

    def _rate_dates(self, on: dt.date) -> list[dt.date]:
        """Candidate rate dates, best first: latest <= on, then nearest overall."""
        prior = [d for d in self.dates if d <= on]
        ordered = list(reversed(prior)) or []
        rest = sorted((d for d in self.dates if d > on))
        return ordered + rest

    @lru_cache(maxsize=None)
    def _factor(self, rate_date: dt.date, src: str, dst: str) -> float | None:
        graph = self.by_date[rate_date]
        if src not in graph:
            return None
        seen = {src: 1.0}
        q = deque([src])
        while q:
            cur = q.popleft()
            if cur == dst:
                return seen[cur]
            for nxt, r in graph[cur].items():
                if nxt not in seen:
                    seen[nxt] = seen[cur] * r
                    q.append(nxt)
        return seen.get(dst)

    def convert(self, amount: float, src: str, dst: str, on: dt.date) -> float:
        if src == dst:
            return amount
        for rd in self._rate_dates(on):
            f = self._factor(rd, src, dst)
            if f is not None:
                return amount * f
        raise ValueError(f"no FX path {src}->{dst} on {on}")
