import Link from "next/link";
import { STATUS, STATUS_ORDER, fmtDate, humanize, num } from "@/lib/format";
import type { Meta } from "@/lib/types";

export function SectionHead({ n, title, kicker, dark }: { n: string; title: string; kicker: string; dark?: boolean }) {
  return (
    <header className={`section-head${dark ? " is-dark" : ""}`}>
      <span className="section-n">{n}</span>
      <h2 className="section-title">{title}</h2>
      <p className="section-kicker">{kicker}</p>
    </header>
  );
}

export function Masthead({ active }: { active: "planner" | "about" }) {
  return (
    <header className="masthead shell">
      <Link href="/" className="wordmark">
        Buy <em>or</em> Wait?
      </Link>
      <nav className="nav">
        <Link href="/" aria-current={active === "planner" ? "page" : undefined}>
          <span>I</span>Planner
        </Link>
        <Link href="/about" aria-current={active === "about" ? "page" : undefined}>
          <span>II</span>How it works
        </Link>
      </nav>
    </header>
  );
}

const STATIONS = [
  {
    name: "Evidence",
    file: "evidence",
    body: "A model reads receipts and messages into a fixed vocabulary of 17 directives. The only model call, and it never decides anything.",
    ai: true,
  },
  {
    name: "Ledger",
    file: "ledger",
    body: "Drops cancelled, failed, duplicate and non-cash items. Recurring bills repeat on their calendar day; unconfirmed income is never counted.",
  },
  {
    name: "Forecast",
    file: "timeline",
    body: "Projects every bill, paycheque and one-off ninety days forward, end of day.",
  },
  {
    name: "Solver",
    file: "solver",
    body: "Tries full, installment, split and wait plans, retries with the spending cuts you allow, and ranks the safe ones on six keys.",
  },
  {
    name: "Verdict",
    file: "explain",
    body: "Only a plan that keeps your minimum balance on every day of the window is ever recommended.",
  },
];

export function Method() {
  return (
    <section className="section shell" id="method">
      <SectionHead
        n="I"
        title="The Method"
        kicker="It looks like a language problem. It is mostly a cash-flow simulation with a small, well-fenced AI layer."
      />
      <div className="source eyebrow">
        <span>Your inputs</span> balance, income, bills, one-offs, payment terms, messages, receipts
      </div>
      <ol className="stations">
        {STATIONS.map((s, i) => (
          <li key={s.name} className={`station${s.ai ? " is-ai" : ""}`}>
            <span className="station-n">{String(i + 1).padStart(2, "0")}</span>
            <h3 className="station-name">{s.name}</h3>
            <code className="station-file">{s.file}</code>
            <p>{s.body}</p>
            {s.ai && <span className="station-tag">model</span>}
          </li>
        ))}
      </ol>
      <div className="source eyebrow source-out">
        <span>A decision</span> computed in your browser, on every edit
      </div>
    </section>
  );
}

export function Guard({ meta }: { meta: Meta }) {
  return (
    <section className="nero" id="guard">
      <div className="section shell">
        <SectionHead
          n="II"
          title="The Guard"
          kicker="Messages are data, never instructions. Real advance-fee scams were in the test data, and they change nothing."
          dark
        />
        <div className="guard">
          <ol className="layers">
            <li>
              <span>i</span>
              <div>
                <h3>The prompt fences the message</h3>
                <p>Scam or instruction-bearing content must be classified <code>untrusted_ignore</code>, and then nothing is applied.</p>
              </div>
            </li>
            <li>
              <span>ii</span>
              <div>
                <h3>A closed vocabulary</h3>
                <p>The model can only emit one of 17 directive kinds. Anything else is dropped before it reaches your forecast.</p>
              </div>
            </li>
            <li>
              <span>iii</span>
              <div>
                <h3>Grounding, digit by digit</h3>
                <p>
                  Any directive that makes you look richer is discarded unless its figure literally appears in the
                  message.{meta.rejectedDirectives > 0 && <> {meta.rejectedDirectives} directives were rejected this way in testing.</>}
                </p>
              </div>
            </li>
          </ol>
          <div className="tablets">
            {meta.untrusted.map((m) => (
              <figure key={m.id} className="tablet">
                <div className="eyebrow tablet-meta">
                  <span>{humanize(m.source)}</span>
                  <span>{fmtDate(m.sentAt)}</span>
                </div>
                <blockquote>{m.text}</blockquote>
                <figcaption>
                  <span className="stamp">Ignored</span>
                  <span className="tablet-note">No effect on the forecast</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

const SCORE_LABELS: Record<string, string> = {
  affordability_status: "Verdict",
  recommended_payment_method: "Payment method",
  payment_plan: "Payment plan",
  spending_changes_needed: "Spending changes",
  earliest_date_for_full_payment: "Earliest full date",
  amount_within_tol: "Safe amount ±1%",
  amount_safe_to_pay: "Safe amount, exact",
};

export function Record({ meta }: { meta: Meta }) {
  const { n, stats } = meta.score;
  const total = meta.counts.requests;
  return (
    <section className="section shell" id="record">
      <SectionHead n="III" title="The Record" kicker={`Tested on ${n} reference cases with known answers, with nothing hidden.`} />
      <div className="record">
        <div className="scores">
          {Object.keys(SCORE_LABELS).map((k) => (
            <div key={k} className="score">
              <span className="score-label">{SCORE_LABELS[k]}</span>
              <span className="score-bar">
                <i style={{ width: `${(100 * stats[k]) / n}%` }} />
              </span>
              <span className="score-v">
                {stats[k]}
                <small>/{n}</small>
              </span>
            </div>
          ))}
          <p className="record-note">
            Verdicts, methods and plans hold up. Exact safe amounts are the weak point: the forecast usually lands above
            the reference, which spends variable categories more cautiously.
          </p>
        </div>

        <div className="record-side">
          <div className="ledger-card">
            <h4 className="eyebrow">Verdicts across {total} test requests</h4>
            <div className="dist">
              {STATUS_ORDER.map((s) => (
                <i key={s} style={{ flexGrow: meta.status[s] ?? 0, background: STATUS[s].color }} />
              ))}
            </div>
            <ul className="dist-legend">
              {STATUS_ORDER.map((s) => (
                <li key={s}>
                  <i style={{ background: STATUS[s].color }} />
                  <span>{humanize(s)}</span>
                  <b>{meta.status[s] ?? 0}</b>
                </li>
              ))}
            </ul>
          </div>
          <div className="ledger-card">
            <h4 className="eyebrow">Model spend in testing</h4>
            <dl className="spend">
              <div><dt>Calls</dt><dd>{meta.usage.calls}</dd></div>
              <div><dt>Tokens in</dt><dd>{num(meta.usage.inTokens)}</dd></div>
              <div><dt>Tokens out</dt><dd>{num(meta.usage.outTokens)}</dd></div>
              <div><dt>Per decision</dt><dd>0</dd></div>
            </dl>
            <p className="record-note">
              The model only runs when you read a message or a receipt. Every decision itself is free and instant.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="footer shell">
      <span className="footer-mark" aria-hidden>
        Buy or Wait?
      </span>
      <div className="footer-row eyebrow">
        <span>Deterministic forecast · grounded evidence · nothing stored on a server</span>
        <span>Not financial advice</span>
      </div>
    </footer>
  );
}
