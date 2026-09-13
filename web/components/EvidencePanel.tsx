"use client";

import { useEffect, useRef, useState } from "react";
import type { Edit } from "./Planner";
import { Field, NumberInput } from "./fields";
import { type Directive, type Outcome, applyDirectives } from "@/lib/directives";
import { dayOf, isoOf } from "@/lib/engine";
import { humanize, num } from "@/lib/format";
import { type Adjustment, type Scenario, uid } from "@/lib/scenario";

interface Receipt {
  amount: number;
  currency: string | null;
  date: string | null;
  merchant: string;
  direction: "in" | "out";
  category: string;
  confidence: string;
  sourceLine: string;
}

function describe(a: Adjustment) {
  switch (a.kind) {
    case "salary_set_level":
      return `Salary counted as ${num(a.amount)}${a.from ? ` from ${a.from}` : ""}`;
    case "salary_next_only":
      return `Next pay counted as ${num(a.amount)}`;
    case "salary_stop":
      return `Salary stops from ${a.from}`;
    case "recurring_expense_pct":
      return `${humanize(a.category)} ${a.percent > 0 ? "+" : ""}${a.percent}%${a.from ? ` from ${a.from}` : ""}`;
  }
}

/** Phone photos can exceed the upload limit; re-encode large images before sending. */
async function shrink(file: File): Promise<File> {
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return file;
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size < 3_500_000) return file;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.86));
  return blob ? new File([blob], "receipt.jpg", { type: "image/jpeg" }) : file;
}

async function post(url: string, init: RequestInit) {
  const res = await fetch(url, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? "The request failed.");
  return body;
}

export default function EvidencePanel({
  scenario,
  edit,
  replace,
}: {
  scenario: Scenario;
  edit: Edit;
  replace: (s: Scenario) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"message" | "receipt" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[] | null>(null);
  const [undo, setUndo] = useState<Scenario | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const latest = useRef(scenario);
  useEffect(() => {
    latest.current = scenario;
  }, [scenario]);

  const tomorrow = isoOf(dayOf(scenario.today) + 1);

  async function readMessage() {
    setBusy("message");
    setError(null);
    setOutcomes(null);
    try {
      const body = await post("/api/read-message", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, currency: scenario.currency, today: scenario.today }),
      });
      const before = latest.current;
      const result = applyDirectives(before, body.directives as Directive[]);
      if (result.outcomes.some((o) => o.status === "applied")) {
        setUndo(before);
        replace(result.scenario);
      }
      setOutcomes(result.outcomes);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function readReceipt(file: File) {
    setBusy("receipt");
    setError(null);
    setReceipt(null);
    try {
      const form = new FormData();
      form.append("file", await shrink(file));
      const body: Receipt = await post("/api/extract-receipt", { method: "POST", body: form });
      setReceipt({ ...body, date: body.date && body.date > scenario.today ? body.date : tomorrow });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function addReceipt(as: "once" | "monthly") {
    if (!receipt) return;
    const date = receipt.date ?? tomorrow;
    edit((d) => {
      if (as === "once") {
        d.oneOffs.push({ id: uid(), label: receipt.merchant, category: receipt.category, direction: receipt.direction, amount: receipt.amount, date });
      } else {
        d.recurring.push({
          id: uid(),
          label: receipt.merchant,
          category: receipt.category,
          direction: receipt.direction,
          amount: receipt.amount,
          schedule: { every: "month", day: Number(date.slice(8, 10)) },
          flexibility: "fixed",
          minAmount: null,
          confirmed: true,
        });
      }
    });
    setReceipt(null);
  }

  const currencyMismatch = receipt?.currency && receipt.currency !== scenario.currency.toUpperCase();

  return (
    <div className="ai">
      <div className="ai-grid">
        <div className="ai-box">
          <h4>Paste a message</h4>
          <p>An email about a raise, a rent increase, a delayed refund. Scams and unsupported figures are refused.</p>
          <textarea
            className="in"
            value={text}
            maxLength={4000}
            placeholder="“Your monthly salary increases to 5,200 from 1 October…”"
            onChange={(e) => setText(e.target.value)}
          />
          <button type="button" className="btn" disabled={!text.trim() || busy !== null} onClick={readMessage}>
            {busy === "message" ? "Reading…" : "Read message"}
          </button>
        </div>

        <div className="ai-box">
          <h4>Upload a bill or receipt</h4>
          <p>A photo or PDF. The amount is read off the document, then you choose where it goes.</p>
          <label className="drop" data-busy={busy === "receipt" || undefined}>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/heic,application/pdf"
              disabled={busy !== null}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) readReceipt(f);
                e.target.value = "";
              }}
            />
            {busy === "receipt" ? "Reading the document…" : "Choose a file"}
          </label>
        </div>
      </div>

      {error && <p className="ai-error" role="alert">{error}</p>}

      {receipt && (
        <div className="receipt-card">
          <span className="eyebrow">
            Read from document · {receipt.confidence} confidence{receipt.sourceLine && <> · &ldquo;{receipt.sourceLine}&rdquo;</>}
          </span>
          <div className="fields">
            <Field label="What">
              <input className="in" value={receipt.merchant} onChange={(e) => setReceipt({ ...receipt, merchant: e.target.value })} />
            </Field>
            <Field label={`Amount${receipt.currency ? ` · ${receipt.currency}` : ""}`}>
              <NumberInput label="Receipt amount" value={receipt.amount} onChange={(amount) => setReceipt({ ...receipt, amount })} />
            </Field>
            <Field label="Date">
              <input className="in" type="date" min={tomorrow} value={receipt.date ?? tomorrow} onChange={(e) => setReceipt({ ...receipt, date: e.target.value })} />
            </Field>
            <Field label="Type">
              <select className="in" value={receipt.direction} onChange={(e) => setReceipt({ ...receipt, direction: e.target.value as "in" | "out" })}>
                <option value="out">Out</option>
                <option value="in">In</option>
              </select>
            </Field>
          </div>
          {currencyMismatch && (
            <p className="warn">
              This document is in {receipt.currency}, your plan is in {scenario.currency}. Convert the amount before adding it.
            </p>
          )}
          <div className="btn-row">
            <button type="button" className="btn" onClick={() => addReceipt("once")}>Add as one-off</button>
            <button type="button" className="btn btn-ghost" onClick={() => addReceipt("monthly")}>Add as monthly bill</button>
            <button type="button" className="btn btn-ghost" onClick={() => setReceipt(null)}>Discard</button>
          </div>
        </div>
      )}

      {outcomes && (
        <div className="outcomes">
          <div className="outcomes-head">
            <span className="eyebrow">What the message changed</span>
            {undo && (
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  replace(undo);
                  setUndo(null);
                  setOutcomes(null);
                }}
              >
                Undo
              </button>
            )}
          </div>
          {outcomes.length === 0 && <p className="empty-row">Nothing in that message affects your cash.</p>}
          {outcomes.map((o, i) => (
            <div key={i} className={`outcome oc-${o.status}`}>
              <b>{o.status === "applied" ? "Applied" : o.status === "blocked" ? "Refused" : "Noted"}</b>
              <div>
                {o.note}
                {o.directive.evidence_quote && <q>{o.directive.evidence_quote}</q>}
              </div>
            </div>
          ))}
        </div>
      )}

      {scenario.adjustments.length > 0 && (
        <div className="outcomes">
          <span className="eyebrow">Active adjustments from messages</span>
          {scenario.adjustments.map((a) => (
            <div key={a.id} className="outcome oc-applied">
              <b>Active</b>
              <div className="adj">
                <span>
                  {describe(a)}
                  {a.quote && <q>{a.quote}</q>}
                </span>
                <button
                  type="button"
                  className="row-x"
                  aria-label="Remove adjustment"
                  onClick={() => edit((d) => void (d.adjustments = d.adjustments.filter((x) => x.id !== a.id)))}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
