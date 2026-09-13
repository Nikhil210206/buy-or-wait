import { NextResponse } from "next/server";
import { GeminiError, generateJson, sameOrigin } from "@/lib/gemini";
import { grounded } from "@/lib/grounding";
import { KINDS, MESSAGE_PROMPT, MESSAGE_SCHEMA } from "@/lib/prompts";

export const maxDuration = 60;

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const text = str(body.text);
  if (!text || text.length > 4000) {
    return NextResponse.json({ error: "Paste a message of up to 4,000 characters." }, { status: 400 });
  }
  const currency = str(body.currency)?.slice(0, 8) ?? "";
  const today = typeof body.today === "string" && /^\d{4}-\d{2}-\d{2}$/.test(body.today) ? body.today : new Date().toISOString().slice(0, 10);

  try {
    const out = (await generateJson(
      [{ text: MESSAGE_PROMPT + JSON.stringify({ today, home_currency: currency, text }) }],
      MESSAGE_SCHEMA,
    )) as { directives?: unknown };

    const raw = Array.isArray(out?.directives) ? (out.directives as Record<string, unknown>[]) : [];
    // Models occasionally repeat a directive; applying "rent +8%" twice would compound it.
    const seen = new Set<string>();
    const directives = raw
      .filter((d) => typeof d?.kind === "string" && (KINDS as readonly string[]).includes(d.kind as string))
      .filter((d) => {
        const key = JSON.stringify([d.kind, d.amount, d.percent, d.target_category, d.effective_date]);
        return !seen.has(key) && seen.add(key);
      })
      .map((d) => {
        const directive = {
          kind: d.kind as string,
          amount: num(d.amount),
          currency: str(d.currency),
          effective_date: str(d.effective_date),
          percent: num(d.percent),
          target_category: str(d.target_category),
          evidence_quote: str(d.evidence_quote) ?? "",
        };
        return { ...directive, grounded: grounded(directive, text) };
      });
    return NextResponse.json({ directives });
  } catch (e) {
    if (e instanceof GeminiError) return NextResponse.json({ error: e.message }, { status: e.status });
    console.error(e);
    return NextResponse.json({ error: "Something went wrong reading the message." }, { status: 500 });
  }
}
