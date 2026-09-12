"""Number formatting that reproduces the solved samples byte-for-byte.

Two different conventions are used by the ground truth:

* `amount_safe_to_pay` -- plain, trailing zeros stripped  (17229139.2, 603.3, 462)
* amounts inside `payment_plan` -- two decimals when fractional, otherwise a
  bare integer  (620.40, 996.60, 15952906.67, 25256, 68432)
"""
from __future__ import annotations

import datetime as dt


def money_field(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def money_plan(v: float) -> str:
    s = f"{v:.2f}"
    return s[:-3] if s.endswith(".00") else s


def plan_str(payments: list[tuple[dt.date, float]]) -> str:
    if not payments:
        return "none"
    return "|".join(f"{d.isoformat()}:{money_plan(a)}" for d, a in payments)
