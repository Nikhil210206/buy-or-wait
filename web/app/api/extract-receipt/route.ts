import { NextResponse } from "next/server";
import { GeminiError, generateJson, sameOrigin } from "@/lib/gemini";
import { RECEIPT_PROMPT, RECEIPT_SCHEMA } from "@/lib/prompts";

export const maxDuration = 60;

// Vercel caps request bodies at 4.5 MB; the client downsizes photos before upload.
const MAX_BYTES = 4 * 1024 * 1024;
const TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif", "application/pdf"]);

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  let file: FormDataEntryValue | null;
  try {
    file = (await req.formData()).get("file");
  } catch {
    return NextResponse.json({ error: "Invalid upload." }, { status: 400 });
  }
  if (!(file instanceof File)) return NextResponse.json({ error: "Attach an image or PDF." }, { status: 400 });
  if (!TYPES.has(file.type)) return NextResponse.json({ error: "Use a PNG, JPEG, WebP, HEIC or PDF." }, { status: 415 });
  if (file.size > MAX_BYTES) return NextResponse.json({ error: "Keep uploads under 4 MB." }, { status: 413 });

  try {
    const data = Buffer.from(await file.arrayBuffer()).toString("base64");
    const out = (await generateJson(
      [{ inline_data: { mime_type: file.type, data } }, { text: RECEIPT_PROMPT }],
      RECEIPT_SCHEMA,
    )) as Record<string, unknown>;

    const amount = typeof out.amount === "number" && Number.isFinite(out.amount) ? Math.abs(out.amount) : 0;
    if (!amount) return NextResponse.json({ error: "No amount could be read from that document." }, { status: 422 });

    const date = typeof out.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(out.date) ? out.date : null;
    return NextResponse.json({
      amount,
      currency: typeof out.currency === "string" ? out.currency.toUpperCase().slice(0, 8) : null,
      date,
      merchant: typeof out.merchant === "string" ? out.merchant.slice(0, 80) : "Document",
      direction: out.direction === "in" ? "in" : "out",
      category: typeof out.category === "string" ? out.category.toLowerCase().replace(/\s+/g, "_").slice(0, 40) : "other",
      confidence: ["high", "medium", "low"].includes(out.confidence as string) ? out.confidence : "low",
      sourceLine: typeof out.source_line === "string" ? out.source_line.slice(0, 160) : "",
    });
  } catch (e) {
    if (e instanceof GeminiError) return NextResponse.json({ error: e.message }, { status: e.status });
    console.error(e);
    return NextResponse.json({ error: "Something went wrong reading the document." }, { status: 500 });
  }
}
