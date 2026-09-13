# AI Judge interview — prep notes

30 minutes, camera on, opens after submission and stays open 12 hours.
The judge has your submission and will probe your approach, your decisions, and
how you used AI. Below is what you actually built, in the order you'd want to
explain it. Not a script — you should be able to defend any of it.

## The one-sentence version

It looks like an LLM problem but it's mostly a deterministic 90-day cash-flow
simulation; the model is used only where language and vision are genuinely
required — 16 receipt images and 215 messages — and everything it produces is
re-checked by code before it can affect a recommendation.

## Why that split

Three facts from the data drove it:

- Exactly **16 events have a blank amount**, each linked to exactly one image.
  That bounds the vision work at 16 calls — it can't grow with the request count.
- **215 messages, one per user**, from ~30 templated archetypes. Batched 15 at a
  time, that's ~15 calls, not 215.
- Everything else — balances, recurrence, options, ranking — is arithmetic with
  a published rule set. Handing arithmetic to a model would make it *less*
  accurate and unverifiable.

Result: model calls scale with **evidence**, not with requests. The marginal
token cost of the 251st request is zero.

## The parts you should be able to defend

**Recurrence detection has two regimes.** Contractual items (rent, utilities,
loan instalments, subscriptions) repeat monthly under a stable description on a
tight cycle. Groceries, transport and dining are a rotating pool of merchant
names drawn weekly or fortnightly. Treating the second group per-description
invents monthly commitments that don't exist — an early version did exactly
that, inventing a monthly "Commuter pass" out of purchases 28/28/70/42 days
apart.

**Income is clustered by day of month.** Users run concurrent streams — a base
salary on the 15th, commission on the 24th — and streams get renamed mid-history
("Performance commission" → "Monthly sales commission"). Day-of-month clustering
separates concurrent streams and survives renames; grouping by description does
neither. An amount-stability test (coefficient of variation) then distinguishes
contractual base pay from variable commission, which matters because several
messages confirm a base salary while saying the commission is unapproved.

**Some signals need no message at all.** `user_05`'s salary row is described as
"Final employer payroll" — employment has ended. That's detected deterministically
from the description, not from an LLM call.

## The untrusted-input question — expect this one

The dataset contains an advance-fee scam: *"You've been selected for a cash
prize. Pay the release charge today to receive the funds."* So the spec's "treat
message and image content as untrusted" is a real requirement. Three layers:

1. **Prompt** — the block is declared as data, never instructions; scam or
   instruction-bearing content must be classified `untrusted_ignore`.
2. **Enum** — the model can only emit directives from a fixed 17-value set.
   Anything else is dropped before it reaches the ledger.
3. **Grounding guard** — the important one, because it doesn't trust the model at
   all. Every directive that makes the user look *better off* (a higher pay
   level, extra income) is discarded unless the figure it claims literally
   appears in the source text, compared digit-wise so `42,750,000` and
   `42750000` match. A hallucinated or injected number cannot reach the forecast.

It already caught a real case: a message announcing that "a new recurring
childcare payment begins" without stating an amount. The model proposed a
`new_recurring_expense`; the guard rejected it because there was no figure to
ground. Note the direction — this one would have made the user look *worse* off,
and it was still rejected, because the rule is "no unsupported figures," not
"no inconvenient ones."

**No message can change control flow.** The worst a hostile one can do is be ignored.

## Things you should volunteer, not hide

- **The 25 solved samples are a test set, and they caught real bugs.** The
  clearest: a rent receipt reads *Total 2,00,000 / Amount Received 1,00,000 /
  Balance Due 1,00,000*, and the ledger entry is "Outstanding rent balance" — the
  right figure is the balance due. The first prompt asked for the grand total and
  got 200,000, which flipped `request_16` from affordable to not affordable. The
  prompt now receives the ledger entry's description and direction.
- **Two hyperparameters are fitted, and only two**: a conservatism multiplier on
  variable spend (1.05) and a history window (180 days), selected by
  `evaluation/calibrate.py` against the samples. AGENTS.md asks for variable
  spending to be forecast conservatively without saying how much. There is **no
  per-request or per-user branching anywhere in the code** — the rules forbid it.
- **Residual error is irreducible in part.** Discretionary spend is randomly
  drawn; the future draws are unknowable. The median prediction/ground-truth
  ratio is ~1.03, so the typical case is close to unbiased; the misses are in a
  tail, not a systematic skew.

## The free-tier quota story — a good answer to "what went wrong"

Gemini's free tier meters `GenerateRequestsPerDayPerProjectPerModel` at 20 —
20 requests per day, **per model**. Backing off on one model can never clear
that. The extractor instead works through a pool of ten models and rotates on
both per-day exhaustion and per-minute limits. Throughput went from roughly one
batch every two minutes to one every few seconds. That's an engineering answer,
not a billing one.

## Numbers to have ready

Check `code/evaluation/usage_report.md` for the final figures before the call:
model calls, total tokens, cost per request. Also be ready for "how long does a
full run take" — after the evidence cache exists, `code/main.py` over all 250
requests is pure computation and calls no model at all.
