/**
 * The user's financial situation as entered in the planner. Every figure is in
 * the scenario's own currency; the engine never converts.
 */

export type Flexibility = "fixed" | "reducible" | "stoppable" | "reducible_or_stoppable";

/** Monthly items land on a calendar day (clamped to short months); others repeat every N days. */
export type Schedule =
  | { every: "month"; day: number; from?: string | null }
  | { every: number; next: string };

export interface Recurring {
  id: string;
  label: string;
  category: string;
  direction: "in" | "out";
  amount: number;
  schedule: Schedule;
  flexibility: Flexibility;
  /** Lowest amount a reducible item can be cut to. */
  minAmount: number | null;
  /** Unconfirmed income is never counted. */
  confirmed: boolean;
}

export interface OneOff {
  id: string;
  label: string;
  category: string;
  direction: "in" | "out";
  amount: number;
  date: string;
}

export interface Offer {
  id: string;
  count: number;
  amount: number;
  first: string;
  every: number;
  fee: number;
  total: number;
}

type AdjustmentBody =
  | { kind: "salary_set_level"; amount: number; from: string | null; targetId: string | null }
  | { kind: "salary_next_only"; amount: number }
  | { kind: "salary_stop"; from: string }
  | { kind: "recurring_expense_pct"; category: string; percent: number; from: string | null };

/** Evidence from messages that changes how existing items project forward. */
export type Adjustment = AdjustmentBody & { id: string; quote: string };

export interface Scenario {
  version: 1;
  currency: string;
  today: string;
  balance: number;
  minimum: number;
  recurring: Recurring[];
  oneOffs: OneOff[];
  request: {
    label: string;
    amount: number;
    deadline: string | null;
    allowsPartial: boolean;
  };
  methods: { full: boolean; installments: boolean; partial: boolean };
  /** null = no limit on the number of installments. */
  maxInstallments: number | null;
  /** Whether paying the full amount today is on offer at all. */
  fullAvailableToday: boolean;
  offers: Offer[];
  adjustments: Adjustment[];
}

export const CATEGORIES = [
  "salary",
  "rent",
  "housing",
  "utilities",
  "groceries",
  "transport",
  "debt_repayment",
  "insurance",
  "education",
  "healthcare",
  "family_support",
  "dining",
  "entertainment",
  "shopping",
  "streaming",
  "subscriptions",
  "travel",
  "other",
];

export const uid = () => Math.random().toString(36).slice(2, 10);

export function todayIso() {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function blankScenario(today = todayIso()): Scenario {
  return {
    version: 1,
    currency: "USD",
    today,
    balance: 0,
    minimum: 0,
    recurring: [],
    oneOffs: [],
    request: { label: "", amount: 0, deadline: null, allowsPartial: true },
    methods: { full: true, installments: true, partial: true },
    maxInstallments: null,
    fullAvailableToday: true,
    offers: [],
    adjustments: [],
  };
}
