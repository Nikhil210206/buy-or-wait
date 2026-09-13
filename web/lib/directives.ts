/**
 * Turns directives read from a message into concrete edits to the scenario.
 *
 * Mirrors Evidence.adjustments_for in code/evidence.py, except that where the
 * dataset links a message to a specific ledger row, the planner has no such
 * link, so those directives are surfaced for the user to act on instead.
 */
import { dayOf } from "./engine";
import { type Scenario, uid } from "./scenario";

export interface Directive {
  kind: string;
  amount: number | null;
  currency: string | null;
  effective_date: string | null;
  percent: number | null;
  target_category: string | null;
  evidence_quote: string;
  grounded: boolean;
}

export interface Outcome {
  directive: Directive;
  status: "applied" | "blocked" | "info";
  note: string;
}

const isIso = (s: string | null): s is string => !!s && /^\d{4}-\d{2}-\d{2}$/.test(s);
const category = (s: string | null) => (s ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_") || null;

function largestSalary(s: Scenario) {
  return s.recurring
    .filter((r) => r.category === "salary" && r.direction === "in")
    .sort((a, b) => b.amount - a.amount)[0];
}

export function applyDirectives(input: Scenario, directives: Directive[]): { scenario: Scenario; outcomes: Outcome[] } {
  if (directives.some((d) => d.kind === "untrusted_ignore")) {
    return {
      scenario: input,
      outcomes: directives.map((d) => ({
        directive: d,
        status: "blocked",
        note: "Reads like a scam or an attempt to instruct the reader. Nothing was changed.",
      })),
    };
  }

  const s: Scenario = structuredClone(input);
  const outcomes: Outcome[] = [];
  const add = (directive: Directive, status: Outcome["status"], note: string) => outcomes.push({ directive, status, note });

  for (const d of directives) {
    if (!d.grounded) {
      add(d, "blocked", "The figure it claims is not written in the message, so the grounding guard dropped it.");
      continue;
    }
    if (d.amount !== null && d.currency && d.currency.toUpperCase() !== s.currency.toUpperCase()) {
      add(d, "info", `Stated in ${d.currency.toUpperCase()}. Convert to ${s.currency} and enter it by hand.`);
      continue;
    }
    const eff = isIso(d.effective_date) ? d.effective_date : null;
    const quote = d.evidence_quote;
    const salary = largestSalary(s);

    switch (d.kind) {
      case "salary_set_level":
        if (!d.amount || !salary) {
          add(d, "info", "Add your salary under income first, then read the message again.");
          break;
        }
        s.adjustments.push({ id: uid(), kind: "salary_set_level", amount: d.amount, from: eff, targetId: salary.id, quote });
        add(d, "applied", `${salary.label} becomes ${d.amount.toLocaleString("en-US")}${eff ? ` from ${eff}` : ""}.`);
        break;
      case "salary_next_only":
        if (!d.amount) break;
        s.adjustments.push({ id: uid(), kind: "salary_next_only", amount: d.amount, quote });
        add(d, "applied", `Your next pay is counted as ${d.amount.toLocaleString("en-US")}.`);
        break;
      case "salary_stop":
        s.adjustments.push({ id: uid(), kind: "salary_stop", from: eff ?? s.today, quote });
        add(d, "applied", `Salary is no longer counted${eff ? ` from ${eff}` : ""}.`);
        break;
      case "salary_shift":
        if (!eff || !salary) {
          add(d, "info", "Move the date of your next pay by hand.");
          break;
        }
        salary.schedule =
          salary.schedule.every === "month"
            ? { every: "month", day: Number(eff.slice(8, 10)), from: eff }
            : { every: salary.schedule.every, next: eff };
        add(d, "applied", `${salary.label} now next arrives on ${eff}.`);
        break;
      case "salary_exclude_unconfirmed": {
        const others = s.recurring.filter((r) => r.direction === "in" && r !== salary && r.confirmed);
        others.forEach((r) => (r.confirmed = false));
        add(d, others.length ? "applied" : "info", others.length ? `Stopped counting ${others.map((r) => r.label).join(", ")}.` : "No variable income to exclude.");
        break;
      }
      case "income_one_off":
        if (!d.amount || !eff || dayOf(eff) <= dayOf(s.today)) {
          add(d, "info", "No future date was stated, so it is not counted.");
          break;
        }
        s.oneOffs.push({ id: uid(), label: "Confirmed payment (from message)", category: "salary", direction: "in", amount: d.amount, date: eff });
        add(d, "applied", `Added ${d.amount.toLocaleString("en-US")} arriving ${eff}.`);
        break;
      case "recurring_expense_pct": {
        const cat = category(d.target_category);
        if (!cat || d.percent === null) break;
        s.adjustments.push({ id: uid(), kind: "recurring_expense_pct", category: cat, percent: d.percent, from: eff, quote });
        add(d, "applied", `${cat.replace(/_/g, " ")} changes by ${d.percent > 0 ? "+" : ""}${d.percent}%${eff ? ` from ${eff}` : ""}.`);
        break;
      }
      case "new_recurring_expense": {
        const cat = category(d.target_category) ?? "other";
        if (!d.amount) break;
        const start = eff && dayOf(eff) > dayOf(s.today) ? eff : null;
        s.recurring.push({
          id: uid(),
          label: `New ${cat.replace(/_/g, " ")} (from message)`,
          category: cat,
          direction: "out",
          amount: d.amount,
          schedule: { every: "month", day: Number((start ?? s.today).slice(8, 10)), from: start },
          flexibility: "fixed",
          minAmount: null,
          confirmed: true,
        });
        add(d, "applied", `Added a monthly ${cat.replace(/_/g, " ")} of ${d.amount.toLocaleString("en-US")}.`);
        break;
      }
      case "expense_amend":
      case "expense_cancel":
      case "expense_delay":
        add(d, "info", "Update the matching bill or one-off by hand.");
        break;
      case "income_unconfirmed":
      case "pending_credit_ignore":
        add(d, "info", "Not counted until the money actually arrives.");
        break;
      default:
        add(d, "info", "No effect on your cash.");
    }
  }
  return { scenario: s, outcomes };
}
