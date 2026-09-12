# Buy or Wait? — HackerRank Orchestrate, September 2026

An AI financial agent that decides, for each request in `dataset/requests.csv`,
whether the user can safely afford it — and if not today, on what terms.

## Run it

```bash
cp .env.example .env          # add GEMINI_API_KEY
python3 code/extract.py --images --messages   # AI evidence passes (cached)
python3 code/main.py                          # writes ./output.csv
```

Python 3.11+. No third-party packages — the model clients are plain `urllib`.
`code/main.py` alone is enough to reproduce `output.csv` once
`code/cache/` is populated; the solver never calls a model.

```bash
python3 code/evaluation/score.py             # score against the 25 solved samples
python3 code/evaluation/score.py --check-gt  # verify our contract reading vs ground truth
python3 code/evaluation/report.py            # regenerate evaluation/usage_report.md
```

## Approach

The task looks like an LLM problem but is mostly a **deterministic cash-flow
simulation** wrapped around a small, high-leverage AI layer. Splitting it that
way is the central design decision: it puts the arithmetic somewhere it can be
verified, and confines the model to the part that genuinely needs language and
vision.

```
CSVs ──► ledger ──► 90-day forecast ──► solver ──► verifier ──► output.csv
            ▲                              │
   evidence ─┘                             │
  (images + messages, via Gemini)   ranked candidate plans
```

**1. Evidence (`evidence.py`) — the only place a model is used.**
Exactly 16 events have a blank `amount`, each linked to one PNG, so the vision
pass is bounded at 16 calls. The 215 messages are batched into ~36 calls and
reduced to directives from a fixed 17-value enum.

**2. Ledger (`ledger.py`) — reconstruct the financial position.**
Cancelled, failed and unrealized rows drop out; non-cash investment valuations
never count as cash; pending *credits* (refunds, prize money, gig payouts) are
excluded until they settle while pending *debits* are reserved; a pending debit
linked to an already-settled parent of the same amount is a duplicate charge and
is dropped.

Recurrence is detected in two regimes, because that is what the data contains:

- *contractual* — rent, utilities, loan instalments, subscriptions repeat
  monthly under a stable `description` on a tight cycle.
- *pooled* — groceries, transport and dining are a rotating pool of merchant
  names drawn weekly or fortnightly within a category. Treating these
  per-description invents monthly commitments that do not exist.

Income is clustered **by day of month**, which separates concurrent streams (a
base salary on the 15th plus commission on the 24th) and survives a stream being
renamed mid-history. Terminal descriptions such as *"Final employer payroll"*
end a stream deterministically, with no message required.

**3. Solver (`solver.py`) — enumerate, check, rank.**
`amount_safe_to_pay` is the deepest point of the 90-day balance path less the
user's minimum, capped at the requested amount. `earliest_date_for_full_payment`
is the first day a single full payment leaves the rest of the window above the
minimum — computed independently of the user's method preferences, as the spec
requires. Every eligible plan (full payment, each permitted installment option,
partial payment, wait) is safety-checked; unsafe plans are retried against
subsets of permitted spending changes. Survivors are ranked by the spec's six
keys in order: completes by the deadline, no spending changes, lowest total
paid, earliest start, fewest payments, lowest `payment_option_id`.

**4. Verifier (`verify.py`) — a hard gate, not a warning.**
`main.py` refuses to write `output.csv` if any row violates the contract:
bounds on `amount_safe_to_pay`, installment plans matching a supplied option
exactly, partial plans summing to the requested amount, `affordable_now`
implying `earliest == request_date`, and spending changes restricted to
flexible, non-protected, user-permitted events. Running
`score.py --check-gt` puts the 25 official answers through the same verifier, so
the contract reading is validated against ground truth rather than assumed.

## Treating messages and images as untrusted

The dataset contains an advance-fee scam ("*You've been selected for a cash
prize. Pay the release charge today to receive the funds*"), so this is a real
requirement rather than a formality. Three layers:

1. The extraction prompt states that the block is data, never instructions, and
   that scam or instruction-bearing content must be classified `untrusted_ignore`.
2. The model can only emit directives from a fixed enum; anything else is
   dropped before it reaches the ledger.
3. A **grounding guard** (`evidence.grounded`) independently re-checks every
   directive against the message text. Any directive that makes the user look
   better off — a higher pay level, extra income — is discarded unless the
   figure it claims literally appears in the source, compared digit-wise so
   `42,750,000` and `42750000` match. A hallucinated or injected number cannot
   reach the forecast.

No message can alter control flow. The worst a hostile one can do is be ignored.

## Layout

```
code/
  main.py        entry point
  loaders.py     typed CSV loading
  fx.py          dated currency conversion (BFS over the sparse rate graph)
  evidence.py    AI evidence layer + grounding guard
  ledger.py      dedup, recurrence detection, 90-day projection
  solver.py      plan enumeration, safety checks, ranking
  explain.py     decision_explanation templates
  verify.py      output contract gate
  llm.py         Gemini / xAI clients + token ledger
  extract.py     runs and caches the evidence passes
  evaluation/
    score.py     self-scoring against sample_requests.csv
    report.py    generates usage_report.md
    usage_report.md
```

No secrets are committed; keys are read from `.env` (gitignored) or the
environment. No per-`request_id` or per-`user_id` branching exists anywhere in
the code.
