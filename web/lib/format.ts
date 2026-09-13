import type { Status } from "./types";

const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const cents = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const short = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const num = (n: number) =>
  (Math.abs(n - Math.round(n)) < 0.005 ? whole : cents).format(n);

export const money = (n: number, currency: string) => `${currency} ${num(n)}`;

export const compact = (n: number) => short.format(n);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { y, m, d };
}

export function fmtDate(iso: string) {
  const { y, m, d } = parts(iso);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function shortDate(iso: string) {
  const { m, d } = parts(iso);
  return `${d} ${MONTHS[m - 1]}`;
}

const utc = (iso: string) => {
  const { y, m, d } = parts(iso);
  return Date.UTC(y, m - 1, d);
};

export const addDays = (iso: string, n: number) =>
  new Date(utc(iso) + n * 86_400_000).toISOString().slice(0, 10);

export const daysBetween = (a: string, b: string) => Math.round((utc(b) - utc(a)) / 86_400_000);

export const humanize = (s: string) => s.replace(/_/g, " ");

export const lotNo = (id: string) => id.split("_").pop()!.padStart(3, "0");

export const STATUS: Record<Status, { word: string; tail: string; label: string; color: string }> = {
  affordable_now: { word: "Buy", tail: "today, in full", label: "Now", color: "var(--now)" },
  affordable_with_plan: { word: "Buy", tail: "on a plan", label: "Plan", color: "var(--plan)" },
  affordable_later: { word: "Wait", tail: "then pay in full", label: "Later", color: "var(--later)" },
  not_affordable: { word: "Pass", tail: "not safely affordable", label: "No", color: "var(--no)" },
};

export const STATUS_ORDER: Status[] = [
  "affordable_now",
  "affordable_with_plan",
  "affordable_later",
  "not_affordable",
];
