/**
 * The decision engine, ported from code/ledger.py + code/solver.py + code/explain.py.
 *
 * Deterministic and dependency-free so it runs in the browser on every edit.
 * scripts/check-engine.ts replays all 250 dataset requests through it and
 * compares against output.csv; keep the two implementations in step.
 */
import type { Offer, Scenario, Schedule } from "./scenario";

export const HORIZON = 90;
const EPS = 1e-6;
const MS = 86_400_000;

// ---------------------------------------------------------------- calendar

export function dayOf(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / MS);
}

export const isoOf = (day: number) => new Date(day * MS).toISOString().slice(0, 10);

const validIso = (s: string | null | undefined): s is string =>
  !!s && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(dayOf(s));

/** Day `anchor` of month `m` (0-based, may overflow), clamped to the month's length. */
function anchored(y: number, m: number, anchor: number): number {
  const len = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return Math.round(Date.UTC(y, m, Math.min(anchor, len)) / MS);
}

/** Occurrence days of a schedule within [start, end]. */
export function occurrences(s: Schedule, start: number, end: number): number[] {
  const out: number[] = [];
  if (s.every === "month") {
    const anchor = Math.max(1, Math.min(31, Math.round(s.day) || 1));
    const lower = validIso(s.from) ? Math.max(start, dayOf(s.from)) : start;
    const t = new Date(lower * MS);
    const y = t.getUTCFullYear();
    let m = t.getUTCMonth();
    if (anchored(y, m, anchor) < lower) m++;
    for (let d = anchored(y, m, anchor); d <= end; d = anchored(y, ++m, anchor)) out.push(d);
    return out;
  }
  const step = Math.round(s.every);
  if (!(step > 0) || !validIso(s.next)) return out;
  let d = dayOf(s.next);
  if (d < start) d += Math.ceil((start - d) / step) * step;
  for (; d <= end; d += step) out.push(d);
  return out;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

// ---------------------------------------------------------------- projection

export interface Flow {
  day: number;
  amount: number;
  ref: string;
  label: string;
  category: string;
  kind: "one-off" | "recurring";
}

export interface Changes {
  stop: ReadonlySet<string>;
  reduce: ReadonlyMap<string, number>;
}

const NO_CHANGES: Changes = { stop: new Set(), reduce: new Map() };

function largestSalary(s: Scenario): string | null {
  let best: { id: string; amount: number } | null = null;
  for (const r of s.recurring) {
    if (r.category === "salary" && r.direction === "in" && (!best || num(r.amount) > best.amount)) {
      best = { id: r.id, amount: num(r.amount) };
    }
  }
  return best?.id ?? null;
}

export function flows(s: Scenario, ch: Changes = NO_CHANGES): Flow[] {
  const today = dayOf(s.today);
  const end = today + HORIZON;

  let stopFrom: number | null = null;
  let nextOnly: number | null = null;
  let level: { from: number | null; amount: number; target: string | null } | null = null;
  const scale: { category: string; factor: number; from: number | null }[] = [];
  for (const a of s.adjustments) {
    if (a.kind === "salary_stop") stopFrom = validIso(a.from) ? dayOf(a.from) : today;
    else if (a.kind === "salary_next_only") nextOnly = num(a.amount);
    else if (a.kind === "salary_set_level")
      level = {
        from: validIso(a.from) ? dayOf(a.from) : null,
        amount: num(a.amount),
        target: a.targetId ?? largestSalary(s),
      };
    else if (a.kind === "recurring_expense_pct")
      scale.push({
        category: a.category,
        factor: 1 + num(a.percent) / 100,
        from: validIso(a.from) ? dayOf(a.from) : null,
      });
  }

  const out: Flow[] = [];

  for (const o of s.oneOffs) {
    if (!validIso(o.date)) continue;
    const d = dayOf(o.date);
    if (!(today < d && d <= end)) continue;
    if (o.category === "salary" && stopFrom !== null && d >= stopFrom) continue;
    const a = num(o.amount);
    out.push({ day: d, amount: o.direction === "in" ? a : -a, ref: o.id, label: o.label, category: o.category, kind: "one-off" });
  }

  for (const r of s.recurring) {
    if (ch.stop.has(r.id)) continue;
    if (r.direction === "in" && !r.confirmed) continue;
    const base = ch.reduce.get(r.id) ?? num(r.amount);
    for (const d of occurrences(r.schedule, today + 1, end)) {
      let a = base;
      for (const sc of scale) {
        if (sc.category === r.category && (sc.from === null || d >= sc.from)) a *= sc.factor;
      }
      if (r.category === "salary") {
        if (stopFrom !== null && d >= stopFrom) continue;
        if (level && r.id === level.target && (level.from === null || d >= level.from)) a = level.amount;
      }
      out.push({ day: d, amount: r.direction === "in" ? a : -a, ref: r.id, label: r.label, category: r.category, kind: "recurring" });
    }
  }

  out.sort((x, y) => x.day - y.day || (x.ref < y.ref ? -1 : x.ref > y.ref ? 1 : 0));

  if (nextOnly !== null) {
    const i = out.findIndex((f) => f.category === "salary" && f.amount > 0);
    if (i >= 0) out[i] = { ...out[i], amount: nextOnly };
  }
  return out;
}

// ---------------------------------------------------------------- timeline

interface Pay {
  day: number;
  amount: number;
}

/** End-of-day balances over the window, with prefix/suffix minima. */
export class Timeline {
  readonly start: number;
  readonly end: number;
  readonly floor: number;
  readonly days: number[];
  readonly bal: number[];
  private readonly pre: number[];
  private readonly suf: number[];

  constructor(s: Scenario, ch: Changes = NO_CHANGES) {
    this.start = dayOf(s.today);
    this.end = this.start + HORIZON;
    this.floor = num(s.minimum);

    const daily = new Map<number, number>();
    for (const f of flows(s, ch)) daily.set(f.day, (daily.get(f.day) ?? 0) + f.amount);
    this.days = [this.start, ...[...daily.keys()].sort((a, b) => a - b)];
    let b = num(s.balance);
    this.bal = [b];
    for (const d of this.days.slice(1)) {
      b += daily.get(d)!;
      this.bal.push(b);
    }

    const n = this.bal.length;
    this.pre = new Array(n);
    this.suf = new Array(n);
    let run = Infinity;
    for (let i = 0; i < n; i++) this.pre[i] = run = Math.min(run, this.bal[i]);
    run = Infinity;
    for (let i = n - 1; i >= 0; i--) this.suf[i] = run = Math.min(run, this.bal[i]);
  }

  /** First index whose day is >= d. */
  private idxFrom(d: number): number {
    let lo = 0;
    let hi = this.days.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.days[mid] < d) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  maxPayableToday(): number {
    return Math.max(0, this.suf[0] - this.floor);
  }

  safeSingle(d: number, amount: number): boolean {
    if (d < this.start || d > this.end) return false;
    // j is the balance carried through day d: the first one the payment reduces.
    const j = this.idxFrom(d + 1) - 1;
    if (j > 0 && this.pre[j - 1] < this.floor - EPS) return false;
    return this.suf[j] - amount >= this.floor - EPS;
  }

  safeSchedule(payments: Pay[]): boolean {
    if (payments.some((p) => p.day > this.end)) return false;
    const extra = new Map<number, number>();
    for (const p of payments) extra.set(p.day, (extra.get(p.day) ?? 0) + p.amount);
    const merged = [...new Set([...this.days, ...extra.keys()])].sort((a, b) => a - b);
    let i = 0;
    let cum = 0;
    for (const d of merged) {
      while (i + 1 < this.days.length && this.days[i + 1] <= d) {
        i++;
        cum = this.bal[i] - this.bal[0];
      }
      let paid = 0;
      for (const [dd, a] of extra) if (dd <= d) paid += a;
      if (this.bal[0] + cum - paid < this.floor - EPS) return false;
    }
    return true;
  }

  earliestFull(amount: number): number | null {
    for (let d = this.start; d <= this.end; d++) if (this.safeSingle(d, amount)) return d;
    return null;
  }

  /** Balance at the end of each day of the window, after the given payments. */
  daily(payments: Pay[] = []): number[] {
    const out: number[] = [];
    let i = 0;
    for (let k = 0; k <= HORIZON; k++) {
      const d = this.start + k;
      while (i + 1 < this.days.length && this.days[i + 1] <= d) i++;
      let paid = 0;
      for (const p of payments) if (p.day <= d) paid += p.amount;
      out.push(this.bal[i] - paid);
    }
    return out;
  }
}

// ---------------------------------------------------------------- solver

export type Status = "affordable_now" | "affordable_with_plan" | "affordable_later" | "not_affordable";
export type Method = "full_payment" | "installments" | "partial_payment" | "wait";

export interface Change {
  id: string;
  kind: "stop" | "reduce_to";
  newAmount: number | null;
  label: string;
  category: string;
}

export interface Candidate {
  method: Method;
  payments: { date: string; amount: number }[];
  total: number;
  changes: Change[];
  offerId: string | null;
  safe: boolean;
  note: string;
}

export interface Decision {
  status: Status;
  method: Method | "not_recommended";
  safeToday: number;
  earliest: string | null;
  best: Candidate | null;
  candidates: Candidate[];
  explanation: string;
  forecast: { start: string; base: number[]; withPlan: number[] };
  flows: Flow[];
}

function eligibleChanges(s: Scenario): Change[] {
  const out: Change[] = [];
  for (const r of s.recurring) {
    const f = r.flexibility;
    // Reducing is less disruptive than stopping, so it is tried first.
    if ((f === "reducible" || f === "reducible_or_stoppable") && r.minAmount !== null && r.minAmount < num(r.amount)) {
      out.push({ id: r.id, kind: "reduce_to", newAmount: r.minAmount, label: r.label, category: r.category });
    }
    if (f === "stoppable" || f === "reducible_or_stoppable") {
      out.push({ id: r.id, kind: "stop", newAmount: null, label: r.label, category: r.category });
    }
  }
  return out;
}

function* combinations<T>(items: T[], n: number, from = 0): Generator<T[]> {
  if (n === 0) {
    yield [];
    return;
  }
  for (let i = from; i <= items.length - n; i++) {
    for (const rest of combinations(items, n - 1, i + 1)) yield [items[i], ...rest];
  }
}

function* product<T>(lists: T[][]): Generator<T[]> {
  if (!lists.length) {
    yield [];
    return;
  }
  for (const head of lists[0]) for (const tail of product(lists.slice(1))) yield [head, ...tail];
}

/** Subsets touching each item at most once, smallest first. */
function* changeSets(changes: Change[], maxN = 3): Generator<Change[]> {
  const byItem = new Map<string, Change[]>();
  for (const c of changes) byItem.set(c.id, [...(byItem.get(c.id) ?? []), c]);
  const ids = [...byItem.keys()];
  for (let n = 1; n <= Math.min(maxN, ids.length); n++) {
    for (const combo of combinations(ids, n)) yield* product(combo.map((id) => byItem.get(id)!));
  }
}

function asChanges(set: Change[]): Changes {
  return {
    stop: new Set(set.filter((c) => c.kind === "stop").map((c) => c.id)),
    reduce: new Map(set.filter((c) => c.kind === "reduce_to").map((c) => [c.id, c.newAmount ?? 0])),
  };
}

export function installmentPayments(o: Offer): { date: string; amount: number }[] {
  if (!validIso(o.first)) return [];
  const every = Math.max(0, Math.round(num(o.every)));
  return Array.from({ length: Math.max(0, Math.round(num(o.count))) }, (_, k) => ({
    date: isoOf(dayOf(o.first) + every * k),
    amount: num(o.amount),
  }));
}

export function solve(s: Scenario): Decision {
  const today = dayOf(s.today);
  const amount = num(s.request.amount);
  const deadline = validIso(s.request.deadline) ? dayOf(s.request.deadline) : null;
  const tl = new Timeline(s);

  const safeToday = Math.min(amount, tl.maxPayableToday());
  const earliestDay = tl.earliestFull(amount);

  const offers = s.methods.installments
    ? s.offers.filter((o) => s.maxInstallments === null || o.count <= s.maxInstallments)
    : [];
  const eligible = eligibleChanges(s);
  const candidates: Candidate[] = [];

  const consider = (method: Method, payments: { date: string; amount: number }[], total: number, offer: Offer | null, allowChanges: boolean) => {
    const pays = payments.map((p) => ({ day: dayOf(p.date), amount: p.amount }));
    const base = { method, payments, total, offerId: offer?.id ?? null };
    if (!pays.length) return;
    if (deadline !== null && pays[pays.length - 1].day > deadline) {
      candidates.push({ ...base, changes: [], safe: false, note: "Finishes after your deadline" });
      return;
    }
    if (tl.safeSchedule(pays)) {
      candidates.push({ ...base, changes: [], safe: true, note: "Keeps your minimum as is" });
      return;
    }
    if (allowChanges) {
      for (const set of changeSets(eligible)) {
        if (new Timeline(s, asChanges(set)).safeSchedule(pays)) {
          candidates.push({ ...base, changes: set, safe: true, note: `Safe with ${set.length} spending change${set.length > 1 ? "s" : ""}` });
          return;
        }
      }
    }
    const beyond = pays.some((p) => p.day > tl.end);
    candidates.push({
      ...base,
      changes: [],
      safe: false,
      note: beyond ? "Runs past the 90-day forecast" : "Balance would dip below your minimum",
    });
  };

  if (amount > 0) {
    if (s.methods.full && s.fullAvailableToday) {
      consider("full_payment", [{ date: s.today, amount }], amount, null, true);
    }
    for (const o of offers) consider("installments", installmentPayments(o), num(o.total), o, true);
    if (
      s.methods.partial &&
      s.request.allowsPartial &&
      earliestDay !== null &&
      earliestDay > today &&
      safeToday > 0 &&
      safeToday < amount &&
      (deadline === null || earliestDay <= deadline)
    ) {
      consider(
        "partial_payment",
        [
          { date: s.today, amount: safeToday },
          { date: isoOf(earliestDay), amount: amount - safeToday },
        ],
        amount,
        null,
        false,
      );
    }
    if (s.methods.full && earliestDay !== null && earliestDay > today) {
      consider("wait", [{ date: isoOf(earliestDay), amount }], amount, null, false);
    }
  }

  const offerRank = (c: Candidate) => (c.offerId === null ? (c.method === "full_payment" ? -1 : 1e9) : s.offers.findIndex((o) => o.id === c.offerId));
  const key = (c: Candidate): number[] => [
    deadline === null || dayOf(c.payments[c.payments.length - 1].date) <= deadline ? 0 : 1,
    c.changes.length,
    Math.round(c.total * 100) / 100,
    dayOf(c.payments[0].date),
    c.payments.length,
    offerRank(c),
  ];
  const cmp = (a: number[], b: number[]) => {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
    return 0;
  };
  const best = candidates.filter((c) => c.safe).sort((a, b) => cmp(key(a), key(b)))[0] ?? null;

  let status: Status;
  if (!best) status = "not_affordable";
  else if (best.method === "full_payment" && !best.changes.length) status = "affordable_now";
  else if (best.method === "wait") status = "affordable_later";
  else status = "affordable_with_plan";

  const earliest = status === "affordable_now" ? s.today : earliestDay !== null ? isoOf(earliestDay) : null;
  const planTl = best?.changes.length ? new Timeline(s, asChanges(best.changes)) : tl;

  const decision: Decision = {
    status,
    method: best?.method ?? "not_recommended",
    safeToday,
    earliest,
    best,
    candidates,
    explanation: "",
    forecast: {
      start: s.today,
      base: tl.daily(),
      withPlan: planTl.daily((best?.payments ?? []).map((p) => ({ day: dayOf(p.date), amount: p.amount }))),
    },
    flows: flows(s, best?.changes.length ? asChanges(best.changes) : NO_CHANGES),
  };
  decision.explanation = explain(s, decision);
  return decision;
}

// ---------------------------------------------------------------- explanation

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function amt(cur: string, v: number) {
  const s = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${cur} ${s.endsWith(".00") ? s.slice(0, -3) : s}`;
}

function longDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

function changesSentence(cur: string, changes: Change[]) {
  const parts = changes.map((c, i) => {
    const what = `the ${c.label.toLowerCase()}`;
    if (c.kind === "stop") return `${i === 0 ? "Stop" : "stop"} ${what}`;
    return `${i === 0 ? "Reduce" : "reduce"} ${what} to ${amt(cur, c.newAmount ?? 0)}`;
  });
  return parts.length > 2 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts.join(" and ");
}

function explain(s: Scenario, d: Decision): string {
  const cur = s.currency;
  const floor = amt(cur, num(s.minimum));
  const best = d.best;

  if (best?.method === "full_payment") {
    const total = amt(cur, best.payments[0].amount);
    if (best.changes.length) {
      return `${changesSentence(cur, best.changes)}, then pay ${total} today. This leaves at least ${floor} available.`;
    }
    return `Pay ${total} today. This leaves at least ${floor} available over the next ${HORIZON} days.`;
  }
  if (best?.method === "installments") {
    const lead = best.changes.length ? `${changesSentence(cur, best.changes)}, then use` : "Use";
    return `${lead} ${best.payments.length} installments of ${amt(cur, best.payments[0].amount)}, starting ${longDate(best.payments[0].date)}. This leaves at least ${floor} available.`;
  }
  if (best?.method === "partial_payment") {
    return `Pay ${amt(cur, best.payments[0].amount)} today and the remaining ${amt(cur, best.payments[1].amount)} on ${longDate(best.payments[1].date)}. This completes the full request and keeps the ${floor} minimum protected.`;
  }
  if (best?.method === "wait") {
    return `Pay ${amt(cur, num(s.request.amount))} in full on ${longDate(best.payments[0].date)}. Paying earlier would take the balance below the ${floor} minimum.`;
  }

  const onlyPartial = s.methods.partial && !s.methods.full && !s.methods.installments && s.request.allowsPartial;
  if (d.safeToday > 0 && onlyPartial) {
    return `Do not proceed with the ${amt(cur, num(s.request.amount))} request. Although ${amt(cur, d.safeToday)} is available today, the full amount cannot be completed safely within ${HORIZON} days.`;
  }
  const when = validIso(s.request.deadline) ? longDate(s.request.deadline) : "the deadline";
  return `Do not make this payment by ${when}. None of the available options keeps the ${floor} minimum protected.`;
}
