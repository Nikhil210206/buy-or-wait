# Buy or Wait? — web app

A planner that tells you whether you can safely pay for something now, on a
plan, later, or not at all. You enter your balance, the minimum you want to
keep, your income, bills and one-off items, and the payment terms on offer. The
app projects your cash 90 days ahead and recommends the safest plan, updating
as you type.

## How it is built

- **Decision engine (`lib/engine.ts`).** A TypeScript port of the Python
  ledger, solver and explanation code in `code/`. It runs in the browser, so
  decisions are instant and nothing about your finances leaves the page.
- **AI evidence (`app/api/*`).** Two server routes call Gemini:
  `read-message` turns a pasted email into forecast directives, and
  `extract-receipt` reads the amount off a bill or receipt. Both reuse the
  prompts and the grounding guard from `code/evidence.py`. Scam-like messages
  change nothing, and figures not literally present in the message are dropped.
- **Persistence.** The current scenario is kept in `localStorage`, and "Share
  link" encodes it into the URL fragment. There is no database and no account.
- **Examples.** `public/data/presets.json` holds five real test requests
  converted to planner scenarios, and `meta.json` feeds the How it works page.

## Environment

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | For AI features | Server-side key for the two API routes. Without it the planner still works; the AI panels report that reading is not configured. |
| `GEMINI_MODELS` | No | Comma-separated model pool, tried in order. Defaults to `gemini-3.5-flash,gemini-3.6-flash,gemini-3.5-flash-lite`. |

Copy `.env.example` to `.env.local` for local development.

## Develop

```bash
cd web
npm install
npm run dev
```

## Verify the engine

The TypeScript engine must agree with the Python solver. This converts all 250
test requests into scenarios and replays them against `output.csv`:

```bash
python3 web/scripts/export_presets.py --all /tmp/cases.json
cd web && npx tsx scripts/check-engine.ts /tmp/cases.json
```

Running `export_presets.py` without `--all` just refreshes the presets and stats.

## Deploy on Vercel

1. Import the repository and set **Root Directory** to `web`.
2. Add `GEMINI_API_KEY` under Project Settings → Environment Variables.
3. Deploy. The pages are static; the two API routes run as functions.

The API routes only accept same-origin browser requests. They have no per-user
rate limit, so watch Gemini usage, or add Vercel Firewall rate limiting, if the
site gets real traffic.
