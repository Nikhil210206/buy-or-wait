"use client";

import EvidencePanel from "./EvidencePanel";
import type { Edit } from "./Planner";
import { CategorySelect, Field, NumberInput, ScheduleInput } from "./fields";
import { dayOf, isoOf } from "@/lib/engine";
import { num } from "@/lib/format";
import { type Flexibility, type Recurring, type Scenario, uid } from "@/lib/scenario";

const CURRENCIES = ["USD", "EUR", "GBP", "INR", "IDR", "ZAR", "AUD", "CAD", "SGD", "AED", "JPY", "BRL", "MXN", "NGN", "KES", "PHP"];

const FLEX: { value: Flexibility; label: string }[] = [
  { value: "fixed", label: "Must pay" },
  { value: "reducible", label: "Could reduce" },
  { value: "stoppable", label: "Could stop" },
  { value: "reducible_or_stoppable", label: "Reduce or stop" },
];

function Section({ n, title, hint, children }: { n: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="fsec">
      <header className="fsec-head">
        <span className="fsec-n">{n}</span>
        <div>
          <h3>{title}</h3>
          {hint && <p>{hint}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}

const RemoveButton = ({ onClick, label }: { onClick: () => void; label: string }) => (
  <button type="button" className="row-x" onClick={onClick} aria-label={`Remove ${label || "item"}`}>
    ×
  </button>
);

export default function ScenarioForm({
  scenario: s,
  edit,
  replace,
}: {
  scenario: Scenario;
  edit: Edit;
  replace: (s: Scenario) => void;
}) {
  const tomorrow = isoOf(dayOf(s.today) + 1);
  const setItem = (id: string, patch: Partial<Recurring>) =>
    edit((d) => Object.assign(d.recurring.find((r) => r.id === id)!, patch));
  const removeItem = (id: string) => edit((d) => void (d.recurring = d.recurring.filter((r) => r.id !== id)));

  const addRecurring = (direction: "in" | "out") =>
    edit((d) =>
      void d.recurring.push({
        id: uid(),
        label: "",
        category: direction === "in" ? "salary" : "rent",
        direction,
        amount: 0,
        schedule: { every: "month", day: Number(tomorrow.slice(8, 10)) },
        flexibility: "fixed",
        minAmount: null,
        confirmed: true,
      }),
    );

  const income = s.recurring.filter((r) => r.direction === "in");
  const bills = s.recurring.filter((r) => r.direction === "out");

  return (
    <div className="form">
      <Section n="i" title="What do you want to pay for?">
        <div className="fields">
          <Field label="Item" className="span-2">
            <input
              className="in in-big"
              placeholder="A laptop, a course, a transfer…"
              value={s.request.label}
              onChange={(e) => edit((d) => void (d.request.label = e.target.value))}
            />
          </Field>
          <Field label="Amount">
            <NumberInput big label="Amount" value={s.request.amount} onChange={(v) => edit((d) => void (d.request.amount = v))} />
          </Field>
          <Field label="Currency">
            <select className="in" value={s.currency} onChange={(e) => edit((d) => void (d.currency = e.target.value))}>
              {(CURRENCIES.includes(s.currency) ? CURRENCIES : [s.currency, ...CURRENCIES]).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="Pay by (optional)">
            <input
              className="in"
              type="date"
              min={s.today}
              value={s.request.deadline ?? ""}
              onChange={(e) => edit((d) => void (d.request.deadline = e.target.value || null))}
            />
          </Field>
          <label className="check field-check">
            <input
              type="checkbox"
              checked={s.request.allowsPartial}
              onChange={(e) => edit((d) => void (d.request.allowsPartial = e.target.checked))}
            />
            Can be split into two payments
          </label>
        </div>
      </Section>

      <Section n="ii" title="Where you stand" hint="Your available balance today, and the cushion you never want to go below.">
        <div className="fields">
          <Field label="As of">
            <input className="in" type="date" value={s.today} onChange={(e) => e.target.value && edit((d) => void (d.today = e.target.value))} />
          </Field>
          <Field label={`Available balance · ${s.currency}`}>
            <NumberInput label="Available balance" value={s.balance} onChange={(v) => edit((d) => void (d.balance = v))} />
          </Field>
          <Field label={`Keep at least · ${s.currency}`}>
            <NumberInput label="Minimum balance" value={s.minimum} onChange={(v) => edit((d) => void (d.minimum = v))} />
          </Field>
        </div>
      </Section>

      <Section n="iii" title="Money coming in" hint="Only confirmed income counts. Untick commission or payouts that aren't certain.">
        <div className="rows">
          {income.map((r) => (
            <div key={r.id} className="row row-in">
              <Field label="Source">
                <input className="in" placeholder="Salary" value={r.label} onChange={(e) => setItem(r.id, { label: e.target.value })} />
              </Field>
              <Field label="Amount">
                <NumberInput label="Income amount" value={r.amount} onChange={(v) => setItem(r.id, { amount: v })} />
              </Field>
              <Field label="When">
                <ScheduleInput schedule={r.schedule} today={s.today} onChange={(schedule) => setItem(r.id, { schedule })} />
              </Field>
              <label className="check">
                <input type="checkbox" checked={r.confirmed} onChange={(e) => setItem(r.id, { confirmed: e.target.checked })} />
                Confirmed
              </label>
              <RemoveButton label={r.label} onClick={() => removeItem(r.id)} />
            </div>
          ))}
          {!income.length && <p className="empty-row">No regular income yet.</p>}
        </div>
        <button type="button" className="add" onClick={() => addRecurring("in")}>
          + Add income
        </button>
      </Section>

      <Section n="iv" title="Bills & regular spending" hint="Mark what you'd be willing to cut. Only those are ever suggested.">
        <div className="rows">
          {bills.map((r) => (
            <div key={r.id} className="row row-out">
              <Field label="Bill">
                <input className="in" placeholder="Rent" value={r.label} onChange={(e) => setItem(r.id, { label: e.target.value })} />
              </Field>
              <Field label="Category">
                <CategorySelect value={r.category} onChange={(category) => setItem(r.id, { category })} />
              </Field>
              <Field label="Amount">
                <NumberInput label="Bill amount" value={r.amount} onChange={(v) => setItem(r.id, { amount: v })} />
              </Field>
              <Field label="When">
                <ScheduleInput schedule={r.schedule} today={s.today} onChange={(schedule) => setItem(r.id, { schedule })} />
              </Field>
              <Field label="Flexibility">
                <select
                  className="in"
                  value={r.flexibility}
                  onChange={(e) => {
                    const flexibility = e.target.value as Flexibility;
                    const reducible = flexibility === "reducible" || flexibility === "reducible_or_stoppable";
                    setItem(r.id, {
                      flexibility,
                      minAmount: reducible ? (r.minAmount ?? Math.round(r.amount / 2)) : null,
                    });
                  }}
                >
                  {FLEX.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </Field>
              <RemoveButton label={r.label} onClick={() => removeItem(r.id)} />
              {r.minAmount !== null && (r.flexibility === "reducible" || r.flexibility === "reducible_or_stoppable") && (
                <div className="row-sub">
                  <Field label="Could go as low as">
                    <NumberInput label="Lowest amount" value={r.minAmount} onChange={(v) => setItem(r.id, { minAmount: v })} />
                  </Field>
                </div>
              )}
            </div>
          ))}
          {!bills.length && <p className="empty-row">No bills yet.</p>}
        </div>
        <button type="button" className="add" onClick={() => addRecurring("out")}>
          + Add a bill
        </button>
      </Section>

      <Section n="v" title="One-off items" hint="Anything that lands once in the next 90 days: a refund, a fee, a deposit.">
        <div className="rows">
          {s.oneOffs.map((o) => {
            const set = (patch: Partial<typeof o>) => edit((d) => Object.assign(d.oneOffs.find((x) => x.id === o.id)!, patch));
            return (
              <div key={o.id} className="row row-once">
                <Field label="Date">
                  <input className="in" type="date" min={tomorrow} value={o.date} onChange={(e) => set({ date: e.target.value })} />
                </Field>
                <Field label="What">
                  <input className="in" placeholder="Insurance renewal" value={o.label} onChange={(e) => set({ label: e.target.value })} />
                </Field>
                <Field label="Type">
                  <select className="in" value={o.direction} onChange={(e) => set({ direction: e.target.value as "in" | "out" })}>
                    <option value="out">Out</option>
                    <option value="in">In</option>
                  </select>
                </Field>
                <Field label="Amount">
                  <NumberInput label="One-off amount" value={o.amount} onChange={(v) => set({ amount: v })} />
                </Field>
                <RemoveButton label={o.label} onClick={() => edit((d) => void (d.oneOffs = d.oneOffs.filter((x) => x.id !== o.id)))} />
              </div>
            );
          })}
          {!s.oneOffs.length && <p className="empty-row">Nothing unusual coming up.</p>}
        </div>
        <button
          type="button"
          className="add"
          onClick={() => edit((d) => void d.oneOffs.push({ id: uid(), label: "", category: "other", direction: "out", amount: 0, date: tomorrow }))}
        >
          + Add a one-off
        </button>
      </Section>

      <Section n="vi" title="How you can pay" hint="Which methods you'd accept, and any installment offers from the seller.">
        <div className="fields">
          <label className="check">
            <input type="checkbox" checked={s.methods.full} onChange={(e) => edit((d) => void (d.methods.full = e.target.checked))} />
            Pay in full
          </label>
          <label className="check">
            <input type="checkbox" checked={s.methods.partial} onChange={(e) => edit((d) => void (d.methods.partial = e.target.checked))} />
            Split in two
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={s.methods.installments}
              onChange={(e) => edit((d) => void (d.methods.installments = e.target.checked))}
            />
            Installments
          </label>
          <Field label="Max installments">
            <input
              className="in in-num"
              inputMode="numeric"
              placeholder="No limit"
              value={s.maxInstallments ?? ""}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                edit((d) => void (d.maxInstallments = Number.isFinite(v) && v > 0 ? v : null));
              }}
            />
          </Field>
        </div>

        {s.methods.installments && (
          <>
            <div className="rows rows-offers">
              {s.offers.map((o) => {
                const set = (patch: Partial<typeof o>) =>
                  edit((d) => {
                    const x = d.offers.find((y) => y.id === o.id)!;
                    Object.assign(x, patch);
                    x.total = Math.round(x.count * x.amount * 100) / 100;
                  });
                return (
                  <div key={o.id} className="row row-offer">
                    <Field label="Payments">
                      <NumberInput integer label="Number of payments" value={o.count} onChange={(v) => set({ count: v })} />
                    </Field>
                    <Field label="Each">
                      <NumberInput label="Amount per payment" value={o.amount} onChange={(v) => set({ amount: v })} />
                    </Field>
                    <Field label="First on">
                      <input className="in" type="date" min={s.today} value={o.first} onChange={(e) => set({ first: e.target.value })} />
                    </Field>
                    <Field label="Every (days)">
                      <NumberInput integer label="Days between payments" value={o.every} onChange={(v) => set({ every: v })} />
                    </Field>
                    <Field label="Total">
                      <span className="total">{num(o.total)}</span>
                    </Field>
                    <RemoveButton label="offer" onClick={() => edit((d) => void (d.offers = d.offers.filter((x) => x.id !== o.id)))} />
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              className="add"
              onClick={() =>
                edit((d) => {
                  const count = 3;
                  const amount = Math.round((d.request.amount / count) * 100) / 100;
                  d.offers.push({ id: uid(), count, amount, first: d.today, every: 30, fee: 0, total: Math.round(count * amount * 100) / 100 });
                })
              }
            >
              + Add an installment offer
            </button>
          </>
        )}
      </Section>

      <Section n="vii" title="Messages & receipts" hint="Let the AI read a pay-change email or a bill photo. You see exactly what it changed.">
        <EvidencePanel scenario={s} edit={edit} replace={replace} />
      </Section>
    </div>
  );
}
