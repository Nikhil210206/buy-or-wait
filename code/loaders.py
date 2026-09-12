"""Typed loading of the dataset/ CSVs.

Every record keeps the *raw* string for any amount alongside the parsed float.
`payment_plan` in the output must reproduce payment-option amounts verbatim
(the solved samples show `996.6` rendered as `996.60`), so the raw text matters.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

DATASET = Path(__file__).resolve().parent.parent / "dataset"


def _date(s: str) -> dt.date | None:
    s = (s or "").strip()
    if not s:
        return None
    return dt.date.fromisoformat(s[:10])


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    return float(s)


def _pipe(s: str) -> list[str]:
    return [p.strip() for p in (s or "").split("|") if p.strip()]


@dataclass(frozen=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    protected_categories: list[str]
    reducible_categories: list[str]
    stoppable_categories: list[str]
    payment_methods: list[str]
    max_installment_months: int | None


@dataclass(frozen=True)
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str          # debit | credit | non_cash
    amount: float | None    # None => must be recovered from a linked image
    currency: str
    event_date: dt.date
    settlement_date: dt.date | None
    status: str             # settled | pending | scheduled | cancelled | failed | unrealized
    linked_event_id: str
    flexibility: str        # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: float | None

    @property
    def cash_date(self) -> dt.date:
        """The date the money actually moves."""
        return self.settlement_date or self.event_date

    @property
    def is_flexible(self) -> bool:
        return self.flexibility in ("reducible", "stoppable", "reducible_or_stoppable")

    @property
    def can_stop(self) -> bool:
        return self.flexibility in ("stoppable", "reducible_or_stoppable")

    @property
    def can_reduce(self) -> bool:
        return self.flexibility in ("reducible", "reducible_or_stoppable")


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: dt.date
    request_type: str
    requested_amount: float
    desired_completion_date: dt.date | None
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str            # full_payment | installments
    payment_amount: float
    payment_amount_raw: str
    number_of_payments: int
    first_payment_date: dt.date
    payment_frequency_days: int | None
    financing_fee: float
    total_payable_amount: float


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str
    related_event_id: str
    sent_at: str
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageRef:
    image_id: str
    user_id: str
    request_id: str
    related_event_id: str

    @property
    def path(self) -> Path:
        return DATASET / "media" / "images" / f"{self.image_id}.png"


@dataclass
class Dataset:
    profiles: dict[str, Profile]
    events: list[Event]
    events_by_user: dict[str, list[Event]] = field(default_factory=dict)
    events_by_id: dict[str, Event] = field(default_factory=dict)
    requests: list[Request] = field(default_factory=list)
    options_by_request: dict[str, list[PaymentOption]] = field(default_factory=dict)
    messages_by_user: dict[str, list[Message]] = field(default_factory=dict)
    images: list[ImageRef] = field(default_factory=list)
    images_by_event: dict[str, ImageRef] = field(default_factory=dict)
    rates: list[tuple[dt.date, str, str, float]] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)


def _rows(name: str) -> list[dict]:
    with open(DATASET / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load(dataset_dir: Path | None = None) -> Dataset:
    global DATASET
    if dataset_dir is not None:
        DATASET = Path(dataset_dir)

    profiles = {}
    for r in _rows("financial_profiles.csv"):
        mim = r["max_installment_months"].strip()
        profiles[r["user_id"]] = Profile(
            user_id=r["user_id"],
            home_currency=r["home_currency"],
            current_available_balance=float(r["current_available_balance"]),
            minimum_balance_to_keep=float(r["minimum_balance_to_keep"]),
            financial_priorities=_pipe(r["financial_priorities"]),
            protected_categories=_pipe(r["expense_categories_to_protect"]),
            reducible_categories=_pipe(r["expense_categories_user_is_willing_to_reduce"]),
            stoppable_categories=_pipe(r["expense_categories_user_is_willing_to_stop"]),
            payment_methods=_pipe(r["payment_methods_user_will_consider"]),
            max_installment_months=int(mim) if mim else None,
        )

    events = []
    for r in _rows("financial_events.csv"):
        events.append(Event(
            event_id=r["event_id"], user_id=r["user_id"], event_type=r["event_type"],
            description=r["description"], category=r["category"], direction=r["direction"],
            amount=_num(r["amount"]), currency=r["currency"],
            event_date=_date(r["event_date"]), settlement_date=_date(r["settlement_date"]),
            status=r["status"], linked_event_id=r["linked_event_id"].strip(),
            flexibility=r["flexibility"], minimum_allowed_amount=_num(r["minimum_allowed_amount"]),
        ))

    by_user: dict[str, list[Event]] = {}
    for e in events:
        by_user.setdefault(e.user_id, []).append(e)
    for v in by_user.values():
        v.sort(key=lambda e: (e.cash_date, e.event_id))

    requests = [Request(
        request_id=r["request_id"], user_id=r["user_id"],
        request_date=_date(r["request_date"]), request_type=r["request_type"],
        requested_amount=float(r["requested_amount"]),
        desired_completion_date=_date(r["desired_completion_date"]),
        allows_partial_payment=r["allows_partial_payment"].strip().lower() == "true",
        request_text=r["request_text"],
    ) for r in _rows("requests.csv")]

    opts: dict[str, list[PaymentOption]] = {}
    for r in _rows("request_payment_options.csv"):
        freq = r["payment_frequency_days"].strip()
        o = PaymentOption(
            payment_option_id=r["payment_option_id"], request_id=r["request_id"],
            payment_method=r["payment_method"],
            payment_amount=float(r["payment_amount"]), payment_amount_raw=r["payment_amount"].strip(),
            number_of_payments=int(r["number_of_payments"]),
            first_payment_date=_date(r["first_payment_date"]),
            payment_frequency_days=int(freq) if freq else None,
            financing_fee=float(r["financing_fee"] or 0),
            total_payable_amount=float(r["total_payable_amount"]),
        )
        opts.setdefault(o.request_id, []).append(o)
    for v in opts.values():
        v.sort(key=lambda o: o.payment_option_id)

    msgs: dict[str, list[Message]] = {}
    for r in _rows("messages.csv"):
        m = Message(r["message_id"], r["user_id"], r["request_id"].strip(),
                    r["related_event_id"].strip(), r["sent_at"], r["source_type"], r["message_text"])
        msgs.setdefault(m.user_id, []).append(m)

    images = [ImageRef(r["image_id"], r["user_id"], r["request_id"].strip(),
                       r["related_event_id"].strip()) for r in _rows("images.csv")]

    rates = [(_date(r["rate_date"]), r["from_currency"], r["to_currency"], float(r["rate"]))
             for r in _rows("exchange_rates.csv")]

    return Dataset(
        profiles=profiles, events=events, events_by_user=by_user,
        events_by_id={e.event_id: e for e in events}, requests=requests,
        options_by_request=opts, messages_by_user=msgs, images=images,
        images_by_event={i.related_event_id: i for i in images if i.related_event_id},
        rates=rates, samples=_rows("sample_requests.csv"),
    )
