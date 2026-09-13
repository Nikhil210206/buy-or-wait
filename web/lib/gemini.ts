/** Server-side Gemini client for the API routes. The key never reaches the browser. */

const BASE = "https://generativelanguage.googleapis.com/v1beta";
const DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.6-flash,gemini-3.5-flash-lite";
const ROTATE_ON = new Set([404, 429, 500, 502, 503, 504]);

export class GeminiError extends Error {
  constructor(
    message: string,
    readonly status = 502,
  ) {
    super(message);
  }
}

export type Part = { text: string } | { inline_data: { mime_type: string; data: string } };

function parseJson(text: string): unknown {
  let t = text.trim();
  if (t.startsWith("```")) t = t.replace(/^```[a-zA-Z]*\n?/, "").replace(/`+$/, "").trim();
  try {
    return JSON.parse(t);
  } catch {
    const m = t.match(/\{[\s\S]*\}/);
    if (!m) throw new Error("no JSON object in response");
    return JSON.parse(m[0]);
  }
}

/** Call the first model in the pool that answers, rotating past quota and overload errors. */
export async function generateJson(parts: Part[], schema: object): Promise<unknown> {
  const key = process.env.GEMINI_API_KEY;
  if (!key) throw new GeminiError("AI reading is not configured on this deployment.", 503);
  const models = (process.env.GEMINI_MODELS ?? DEFAULT_MODELS)
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean);

  let last = "no model configured";
  for (const model of models) {
    let res: Response;
    try {
      res = await fetch(`${BASE}/models/${model}:generateContent`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-goog-api-key": key },
        body: JSON.stringify({
          contents: [{ parts }],
          generationConfig: { temperature: 0, response_mime_type: "application/json", response_schema: schema },
        }),
        signal: AbortSignal.timeout(45_000),
      });
    } catch (e) {
      last = `${model}: ${(e as Error).message}`;
      continue;
    }
    if (!res.ok) {
      last = `${model}: HTTP ${res.status}`;
      if (ROTATE_ON.has(res.status)) continue;
      console.error("gemini", last, (await res.text()).slice(0, 300));
      throw new GeminiError("The AI service rejected the request.");
    }
    const body = await res.json();
    const text: string =
      body?.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? "").join("") ?? "";
    try {
      return parseJson(text);
    } catch {
      last = `${model}: unreadable response`;
    }
  }
  console.error("gemini pool exhausted:", last);
  throw new GeminiError("The AI service is busy right now. Try again in a minute.");
}

/** Light abuse protection: browser calls must come from this site. */
export function sameOrigin(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).host === (req.headers.get("x-forwarded-host") ?? req.headers.get("host"));
  } catch {
    return false;
  }
}
