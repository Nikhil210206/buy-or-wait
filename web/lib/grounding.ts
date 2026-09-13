/**
 * Grounding guard, ported from code/evidence.py.
 *
 * Messages are untrusted. Any directive that could make the user look better
 * off must carry a figure that literally appears in the message, compared
 * digit-wise so "42,750,000" and "42750000" match.
 */

const digits = (s: string) => s.replace(/[^0-9]/g, "");

function amountInText(amount: number, text: string) {
  const hay = digits(text);
  const cands = [amount.toFixed(0), amount.toFixed(2), String(amount)];
  return cands.some((c) => digits(c) && hay.includes(digits(c)));
}

const OPTIMISTIC = new Set(["salary_set_level", "salary_next_only", "income_one_off"]);

export interface GroundableDirective {
  kind: string;
  amount?: number | null;
  percent?: number | null;
  evidence_quote?: string | null;
}

export function grounded(d: GroundableDirective, text: string): boolean {
  if (!d.evidence_quote) return false;
  const amount = typeof d.amount === "number" ? d.amount : null;
  if (OPTIMISTIC.has(d.kind) || d.kind === "new_recurring_expense" || d.kind === "expense_amend") {
    if (amount === null || !amountInText(amount, text)) return false;
  }
  if (d.kind === "recurring_expense_pct") {
    if (typeof d.percent !== "number" || !digits(text).includes(digits(String(d.percent)))) return false;
  }
  return true;
}
