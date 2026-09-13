"use client";

import { useState } from "react";
import BalanceChart from "./BalanceChart";
import { type Candidate, type Decision, HORIZON, dayOf, isoOf } from "@/lib/engine";
import { STATUS, daysBetween, fmtDate, humanize, money, num, shortDate } from "@/lib/format";
import type { Scenario } from "@/lib/scenario";

const METHOD: Record<string, string> = {
  full_payment: "Pay in full",
  installments: "Installments",
  partial_payment: "Split payment",
  wait: "Wait, then pay in full",
  not_recommended: "Not recommended",
};

function summary(c: Candidate) {
  const p = c.payments;
  switch (c.method) {
    case "full_payment":
      return `${num(p[0].amount)} on ${shortDate(p[0].date)}`;
    case "installments":
      return `${p.length} × ${num(p[0].amount)} from ${shortDate(p[0].date)}`;
    case "partial_payment":
      return `${num(p[0].amount)} now, ${num(p[1].amount)} on ${shortDate(p[1].date)}`;
    case "wait":
      return `${num(p[0].amount)} on ${shortDate(p[0].date)}`;
  }
}

export default function Verdict({ scenario: s, decision: d, stale }: { scenario: Scenario; decision: Decision; stale: boolean }) {
  const [allFlows, setAllFlows] = useState(false);

  if (!(s.request.amount > 0)) {
    return (
      <aside className="verdict-panel verdict-empty">
        <span className="eyebrow">Verdict</span>
        <p>Enter what you want to pay for, and how much.</p>
        <span className="eyebrow">It updates as you type</span>
      </aside>
    );
  }

  const st = STATUS[d.status];
  const best = d.best;
  const tail = d.status === "affordable_later" && d.earliest ? `until ${fmtDate(d.earliest)}` : st.tail;
  const low = Math.min(...d.forecast.withPlan);
  const lowDay = d.forecast.withPlan.indexOf(low);
  const flows = allFlows ? d.flows : d.flows.slice(0, 8);
  const ordered = [...d.candidates].sort((a, b) => Number(b === best) - Number(a === best) || Number(b.safe) - Number(a.safe));

  return (
    <aside className="verdict-panel" data-stale={stale || undefined} aria-live="polite">
      <div className="eyebrow vp-meta">
        <span>{s.request.label || "Your request"}</span>
        <span>{money(s.request.amount, s.currency)}</span>
        <span>as of {fmtDate(s.today)}</span>
      </div>

      <div className="verdict">
        <span className="verdict-word">
          {st.word}
          <i style={{ background: st.color }} />
        </span>
        <span className="verdict-tail">{tail}</span>
      </div>

      <dl className="figures">
        <div>
          <dt>Safe to pay today</dt>
          <dd>{money(d.safeToday, s.currency)}</dd>
        </div>
        <div>
          <dt>Earliest in full</dt>
          <dd>{d.earliest ? fmtDate(d.earliest) : `Not within ${HORIZON} days`}</dd>
        </div>
        <div>
          <dt>Lowest balance</dt>
          <dd>{money(low, s.currency)}</dd>
          <span className="figure-sub">{lowDay === 0 ? "today" : `on ${shortDate(isoOf(dayOf(s.today) + lowDay))}`}</span>
        </div>
        <div>
          <dt>Deadline</dt>
          <dd>{s.request.deadline ? fmtDate(s.request.deadline) : "None"}</dd>
          {s.request.deadline && <span className="figure-sub">{daysBetween(s.today, s.request.deadline)} days</span>}
        </div>
      </dl>

      <section className="ex-block">
        <div className="ex-block-head">
          <h4 className="eyebrow">Ninety-day balance</h4>
          <ul className="legend">
            <li><i className="lg-line" /> {best ? "With recommendation" : "Projected"}</li>
            {!!best?.changes.length && <li><i className="lg-base" /> Without cuts</li>}
            <li><i className="lg-floor" /> Your minimum</li>
            {best && <li><i className="lg-pay" /> Payment</li>}
          </ul>
        </div>
        <BalanceChart
          start={d.forecast.start}
          base={d.forecast.base}
          withPlan={d.forecast.withPlan}
          floor={s.minimum}
          plan={best?.payments ?? []}
          currency={s.currency}
          planDiffers={!!best?.changes.length}
        />
      </section>

      <p className="explanation">{d.explanation}</p>

      {best && (
        <div className="ex-grid">
          <section className="ex-card">
            <h4 className="eyebrow">Schedule</h4>
            <p className="ex-method">{METHOD[best.method]}</p>
            <ol className="schedule">
              {best.payments.map((p, i) => (
                <li key={p.date + i}>
                  <span className="sch-n">{String(i + 1).padStart(2, "0")}</span>
                  <span className="sch-d">{fmtDate(p.date)}</span>
                  <span className="sch-a">{num(p.amount)}</span>
                </li>
              ))}
              {best.payments.length > 1 && (
                <li className="sch-total">
                  <span />
                  <span className="sch-d">Total</span>
                  <span className="sch-a">{num(best.total)}</span>
                </li>
              )}
            </ol>
          </section>
          <section className="ex-card">
            <h4 className="eyebrow">Spending changes</h4>
            {best.changes.length ? (
              <ul className="changes">
                {best.changes.map((c) => (
                  <li key={c.id}>
                    <span className={`chg-kind chg-${c.kind}`}>{c.kind === "stop" ? "Stop" : "Reduce"}</span>
                    <span className="chg-desc">
                      {c.label || "Unnamed bill"}
                      <small>{humanize(c.category)}</small>
                    </span>
                    <span className="chg-amt">{c.kind === "stop" ? "—" : `→ ${num(c.newAmount ?? 0)}`}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ex-empty">None needed.</p>
            )}
          </section>
        </div>
      )}

      {ordered.length > 0 && (
        <section className="ex-block">
          <h4 className="eyebrow">Every option weighed</h4>
          <ul className="cands">
            {ordered.map((c, i) => (
              <li key={i} className={`cand ${c.safe ? "cand-ok" : "cand-no"}${c === best ? " cand-best" : ""}`}>
                <i aria-label={c.safe ? "safe" : "unsafe"}>{c.safe ? "✓" : "✕"}</i>
                <span className="cand-main">
                  {METHOD[c.method]} · {summary(c)}
                  <small>{c.note}</small>
                </span>
                {c === best && <span className="cand-tag">Chosen</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="ex-block">
        <h4 className="eyebrow">Cash movements in the window · {d.flows.length}</h4>
        {d.flows.length ? (
          <table className="flows">
            <tbody>
              {flows.map((f, i) => (
                <tr key={f.ref + f.day + i}>
                  <td className="flow-d">{shortDate(isoOf(f.day))}</td>
                  <td>
                    {f.label || "Unnamed"}
                    <small>{humanize(f.category)} · {f.kind}</small>
                  </td>
                  <td className={`num ${f.amount > 0 ? "flow-in" : ""}`}>
                    {f.amount > 0 ? "+" : "−"}
                    {num(Math.abs(f.amount))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="ex-empty">No income or bills entered yet.</p>
        )}
        {d.flows.length > 8 && (
          <button className="link-btn" onClick={() => setAllFlows((v) => !v)}>
            {allFlows ? "Show fewer" : `Show all ${d.flows.length}`}
          </button>
        )}
      </section>
    </aside>
  );
}
