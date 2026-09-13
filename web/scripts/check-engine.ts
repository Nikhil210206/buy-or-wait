/**
 * Parity check: the TypeScript engine against the Python solver's output.csv.
 *
 *   python3 web/scripts/export_presets.py --all /tmp/cases.json
 *   npx tsx web/scripts/check-engine.ts /tmp/cases.json
 */
import { readFileSync } from "node:fs";
import { solve } from "../lib/engine";
import type { Scenario } from "../lib/scenario";

interface Case {
  requestId: string;
  expected: Record<string, string>;
  scenario: Scenario;
}

const moneyPlan = (v: number) => {
  const s = v.toFixed(2);
  return s.endsWith(".00") ? s.slice(0, -3) : s;
};

const cases: Case[] = JSON.parse(readFileSync(process.argv[2], "utf8"));
const fields = ["amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"];
const hits = Object.fromEntries(fields.map((f) => [f, 0]));
const misses: string[] = [];
let exact = 0;

for (const c of cases) {
  const d = solve(c.scenario);
  const got: Record<string, string> = {
    amount_safe_to_pay: d.safeToday.toFixed(2),
    affordability_status: d.status,
    recommended_payment_method: d.method,
    payment_plan: d.best ? d.best.payments.map((p) => `${p.date}:${moneyPlan(p.amount)}`).join("|") : "none",
    earliest_date_for_full_payment: d.earliest ?? "",
    spending_changes_needed: d.best?.changes.length
      ? d.best.changes.map((ch) => (ch.kind === "stop" ? `stop:${ch.id}` : `reduce_to:${ch.id}:${moneyPlan(ch.newAmount ?? 0)}`)).join("|")
      : "none",
  };
  let all = true;
  for (const f of fields) {
    const want = c.expected[f];
    const ok = f === "amount_safe_to_pay" ? Math.abs(Number(got[f]) - Number(want)) <= 0.011 : got[f] === want;
    if (ok) hits[f]++;
    else {
      all = false;
      misses.push(`${c.requestId} ${f}\n    got  ${got[f]}\n    want ${want}`);
    }
  }
  if (all) exact++;
}

console.log(`\nTS engine vs output.csv over ${cases.length} requests`);
for (const f of fields) console.log(`  ${f.padEnd(32)} ${hits[f]}/${cases.length}`);
console.log(`  ${"all fields".padEnd(32)} ${exact}/${cases.length}`);
if (misses.length) console.log(`\nfirst mismatches:\n  ${misses.slice(0, 20).join("\n  ")}`);
process.exit(exact === cases.length ? 0 : 1);
