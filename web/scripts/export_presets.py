"""Export example scenarios and project stats for the web app.

    python3 web/scripts/export_presets.py [--all PATH]

Converts dataset requests into the planner's Scenario shape (web/lib/scenario.ts):
recurring series detected by the ledger become recurring items, pending and
scheduled events become one-offs, and message evidence becomes adjustments.

Writes web/public/data/presets.json (a few examples) and meta.json (stats for
the About page). --all also writes every request with its output.csv row, which
web/scripts/check-engine.ts uses to verify the TypeScript engine.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT / "code" / "evaluation"))

import evidence as ev_mod  # noqa: E402
import loaders  # noqa: E402
from ledger import HORIZON_DAYS, Ledger, _next_month, _primary_salary  # noqa: E402

OUT = ROOT / "web" / "public" / "data"


def _naive_monthly(start: dt.date, anchor: int) -> dt.date:
    """What the planner computes for a monthly item with no explicit start."""
    d = dt.date(start.year, start.month, min(anchor, calendar.monthrange(start.year, start.month)[1]))
    return d if d >= start else _next_month(d, anchor)


def _schedule(s, start: dt.date, end: dt.date) -> dict | None:
    first = next(s.occurrences(start, start + dt.timedelta(days=800)), None)
    if first is None or first > end:
        return None
    if 26 <= s.cadence_days <= 32:
        anchor = s.anchor_day or s.last_date.day
        sch = {"every": "month", "day": anchor}
        if _naive_monthly(start, anchor) != first:
            sch["from"] = first.isoformat()
        return sch
    return {"every": s.cadence_days, "next": first.isoformat()}


def _flexibility(ds, prof, s) -> tuple[str, float | None]:
    """Event flexibility narrowed to what this user is willing to change (solver._eligible_changes)."""
    ev = ds.events_by_id.get(s.event_id)
    if ev is None or not ev.is_flexible or ev.category in prof.protected_categories:
        return "fixed", None
    can_reduce = (ev.can_reduce and ev.category in prof.reducible_categories
                  and ev.minimum_allowed_amount is not None and ev.amount is not None
                  and ev.minimum_allowed_amount < ev.amount)
    can_stop = ev.can_stop and ev.category in prof.stoppable_categories
    if can_reduce and can_stop:
        return "reducible_or_stoppable", ev.minimum_allowed_amount
    if can_reduce:
        return "reducible", ev.minimum_allowed_amount
    if can_stop:
        return "stoppable", None
    return "fixed", None


def scenario_for(ds, led, ev, req) -> dict:
    uid = req.user_id
    prof = ds.profiles[uid]
    as_of = req.request_date
    start = as_of + dt.timedelta(days=1)
    end = as_of + dt.timedelta(days=HORIZON_DAYS)
    adj = ev.adjustments_for(led, uid, as_of)
    series = led.series_for(uid, as_of)
    primary = _primary_salary(series)

    def quote(kind: str) -> str:
        for m in ds.messages_by_user.get(uid, []):
            for d in ev.messages.get(m.message_id, []):
                if d.get("kind") == kind and ev_mod.grounded(d, m.message_text):
                    return d.get("evidence_quote") or m.message_text[:140]
        return "From message evidence"

    recurring = []
    for s in series:
        sch = _schedule(s, start, end)
        if sch is None:
            continue
        flex, min_amount = _flexibility(ds, prof, s)
        confirmed = True
        if s.category == "salary":
            confirmed = not ((adj.salary_only_primary and s is not primary)
                             or (adj.drop_unstable_income and not s.stable))
        recurring.append({
            "id": s.event_id, "label": s.description, "category": s.category,
            "direction": "in" if s.direction == "credit" else "out", "amount": s.amount,
            "schedule": sch, "flexibility": flex, "minAmount": min_amount, "confirmed": confirmed,
        })
    for cat, amount, begin, cadence in adj.new_recurring:
        recurring.append({
            "id": f"msg:{cat}", "label": f"New {cat.replace('_', ' ')} (from message)", "category": cat,
            "direction": "out", "amount": amount,
            "schedule": {"every": cadence, "next": max(begin, start).isoformat()},
            "flexibility": "fixed", "minAmount": None, "confirmed": True,
        })

    one_offs = []
    for e in ds.events_by_user.get(uid, []):
        if e.event_id in adj.drop_events or not led.counts_as_cash(e):
            continue
        when = adj.delay_event.get(e.event_id, e.cash_date)
        if not (as_of < when <= end):
            continue
        amt = led.home_amount(e, adj)
        if amt is None:
            continue
        one_offs.append({
            "id": e.event_id, "label": e.description, "category": e.category,
            "direction": "in" if e.direction == "credit" else "out", "amount": amt, "date": when.isoformat(),
        })
    for f in adj.extra_flows:
        if as_of < f.date <= end:
            one_offs.append({
                "id": f.ref, "label": f"Per {f.ref.removeprefix('msg:').replace('_', ' ')}",
                "category": f.category, "direction": "in" if f.amount > 0 else "out",
                "amount": abs(f.amount), "date": f.date.isoformat(),
            })

    adjustments = []
    if adj.salary_primary_level:
        eff, lvl = adj.salary_primary_level
        adjustments.append({"id": "adj-level", "kind": "salary_set_level", "amount": lvl,
                            "from": eff.isoformat() if eff else None,
                            "targetId": primary.event_id if primary else None,
                            "quote": quote("salary_set_level")})
    if adj.salary_next_override is not None:
        adjustments.append({"id": "adj-next", "kind": "salary_next_only", "amount": adj.salary_next_override,
                            "quote": quote("salary_next_only")})
    if adj.salary_stop_from:
        adjustments.append({"id": "adj-stop", "kind": "salary_stop", "from": adj.salary_stop_from.isoformat(),
                            "quote": quote("salary_stop")})
    for i, (cat, factor, eff) in enumerate(adj.series_scale):
        adjustments.append({"id": f"adj-pct-{i}", "kind": "recurring_expense_pct", "category": cat,
                            "percent": round((factor - 1) * 100, 6), "from": eff.isoformat() if eff else None,
                            "quote": quote("recurring_expense_pct")})

    options = ds.options_by_request.get(req.request_id, [])
    full_opt = next((o for o in options if o.payment_method == "full_payment"), None)
    offers = [{
        "id": o.payment_option_id, "count": o.number_of_payments, "amount": o.payment_amount,
        "first": o.first_payment_date.isoformat(), "every": o.payment_frequency_days or 0,
        "fee": o.financing_fee, "total": o.total_payable_amount,
    } for o in options if o.payment_method == "installments"]

    return {
        "version": 1,
        "currency": prof.home_currency,
        "today": as_of.isoformat(),
        "balance": prof.current_available_balance,
        "minimum": prof.minimum_balance_to_keep,
        "recurring": recurring,
        "oneOffs": one_offs,
        "request": {
            "label": req.request_type.replace("_", " ").capitalize(),
            "amount": req.requested_amount,
            "deadline": req.desired_completion_date.isoformat() if req.desired_completion_date else None,
            "allowsPartial": req.allows_partial_payment,
        },
        "methods": {
            "full": "full_payment" in prof.payment_methods,
            "installments": "installments" in prof.payment_methods and prof.max_installment_months is not None,
            "partial": "partial_payment" in prof.payment_methods,
        },
        "maxInstallments": prof.max_installment_months,
        "fullAvailableToday": full_opt is not None,
        "offers": offers,
        "adjustments": adjustments,
    }


PRESET_ORDER = ["affordable_now", "affordable_with_plan", "affordable_with_plan", "affordable_later", "not_affordable"]


def pick_presets(cases: list[dict]) -> list[dict]:
    """One example per verdict (two for plans: installments and spending cuts), favouring rich scenarios."""
    chosen, used, types = [], set(), set()
    wants = [("affordable_now", None), ("affordable_with_plan", "installments"),
             ("affordable_with_plan", "changes"), ("affordable_later", None), ("not_affordable", None)]
    for status, flavour in wants:
        pool = [c for c in cases if c["expected"]["affordability_status"] == status and c["requestId"] not in used
                and c["type"] not in types and c["type"] != "other" and len(c["scenario"]["recurring"]) <= 12]
        if flavour == "installments":
            pool = [c for c in pool if c["expected"]["recommended_payment_method"] == "installments"]
        if flavour == "changes":
            pool = [c for c in pool if c["expected"]["spending_changes_needed"] != "none"]
        pool.sort(key=lambda c: (-len(c["scenario"]["adjustments"]), -len(c["scenario"]["offers"]), c["requestId"]))
        if pool:
            chosen.append(pool[0])
            used.add(pool[0]["requestId"])
            types.add(pool[0]["type"])
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", help="also write every converted request to this path")
    a = ap.parse_args()

    ds = loaders.load()
    ev = ev_mod.load(ds)
    led = Ledger(ds, evidence_amounts=ev.image_amounts())
    with open(ROOT / "output.csv", newline="", encoding="utf-8") as fh:
        outputs = {r["request_id"]: r for r in csv.DictReader(fh)}

    cases = [{
        "requestId": r.request_id,
        "type": r.request_type,
        "question": r.request_text,
        "expected": outputs[r.request_id],
        "scenario": scenario_for(ds, led, ev, r),
    } for r in ds.requests]

    if a.all:
        Path(a.all).write_text(json.dumps(cases))

    OUT.mkdir(parents=True, exist_ok=True)
    presets = [{
        "id": c["requestId"],
        "title": c["scenario"]["request"]["label"],
        "question": c["question"],
        "scenario": c["scenario"],
    } for c in pick_presets(cases)]
    (OUT / "presets.json").write_text(json.dumps(presets, indent=1))

    import pipeline  # noqa: E402
    import score  # noqa: E402
    sds = score.sample_dataset(ds)
    sc = score.score(ds, {r["request_id"]: r for r in pipeline.run(sds, sds.requests)})

    untrusted = []
    for m in (m for msgs in ds.messages_by_user.values() for m in msgs):
        if any(d.get("kind") == "untrusted_ignore" for d in ev.messages.get(m.message_id, [])):
            untrusted.append({"id": m.message_id, "sentAt": m.sent_at, "source": m.source_type, "text": m.message_text})
    usage = json.loads((ROOT / "code" / "cache" / "usage.json").read_text())
    meta = {
        "counts": {"requests": len(ds.requests), "events": len(ds.events),
                   "messages": sum(len(v) for v in ds.messages_by_user.values()), "images": len(ds.images)},
        "status": Counter(r["affordability_status"] for r in outputs.values()),
        "score": {"n": sc["n"], "stats": sc["stats"]},
        "usage": {"calls": len(usage), "inTokens": sum(u.get("in_tokens", 0) for u in usage),
                  "outTokens": sum(u.get("out_tokens", 0) for u in usage)},
        "untrusted": sorted(untrusted, key=lambda m: m["id"]),
        "rejectedDirectives": len(set(ev.rejected)),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"exported {len(presets)} presets ({', '.join(p['id'] for p in presets)}) and meta -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
