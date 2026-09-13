"use client";

import { useState } from "react";
import { dayOf, isoOf } from "@/lib/engine";
import { CATEGORIES, type Schedule } from "@/lib/scenario";
import { humanize } from "@/lib/format";

const shown = (v: number) => (v ? String(Math.round(v * 100) / 100) : "");

/** A number field that lets people type freely ("0.", "12.") while reporting parsed values. */
export function NumberInput({
  value,
  onChange,
  label,
  big,
  integer,
  placeholder = "0",
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  big?: boolean;
  integer?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState(shown(value));
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    if ((parseFloat(text) || 0) !== value) setText(shown(value));
  }
  return (
    <input
      className={`in in-num${big ? " in-big" : ""}`}
      type="text"
      inputMode={integer ? "numeric" : "decimal"}
      aria-label={label}
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        const t = e.target.value.replace(/[^\d.,-]/g, "").replace(/,/g, "");
        setText(t);
        const v = integer ? parseInt(t, 10) : parseFloat(t);
        onChange(Number.isFinite(v) ? Math.max(0, v) : 0);
      }}
    />
  );
}

export function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`field${className ? ` ${className}` : ""}`}>
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

export function CategorySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const options = CATEGORIES.includes(value) ? CATEGORIES : [value, ...CATEGORIES];
  return (
    <select className="in" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((c) => (
        <option key={c} value={c}>
          {humanize(c)}
        </option>
      ))}
    </select>
  );
}

export function ScheduleInput({
  schedule,
  today,
  onChange,
}: {
  schedule: Schedule;
  today: string;
  onChange: (s: Schedule) => void;
}) {
  const tomorrow = isoOf(dayOf(today) + 1);
  const mode = schedule.every === "month" ? "month" : schedule.every === 14 ? "14" : schedule.every === 7 ? "7" : "custom";
  const next = schedule.every === "month" ? null : schedule.next;

  function setMode(m: string) {
    const start = next ?? (schedule.every === "month" && schedule.from ? schedule.from : tomorrow);
    if (m === "month") onChange({ every: "month", day: Number(start.slice(8, 10)) });
    else if (m === "custom") onChange({ every: schedule.every === "month" ? 30 : schedule.every, next: start });
    else onChange({ every: Number(m), next: start });
  }

  return (
    <div className={`sched${mode === "custom" ? " sched-3" : ""}`}>
      <select className="in" aria-label="How often" value={mode} onChange={(e) => setMode(e.target.value)}>
        <option value="month">Monthly</option>
        <option value="14">Every 2 weeks</option>
        <option value="7">Weekly</option>
        <option value="custom">Every N days</option>
      </select>
      {schedule.every === "month" ? (
        <NumberInput
          label="Day of month"
          integer
          placeholder="day"
          value={schedule.day}
          onChange={(v) => onChange({ ...schedule, day: Math.min(31, Math.max(1, v || 1)) })}
        />
      ) : (
        <>
          {mode === "custom" && (
            <NumberInput
              label="Every how many days"
              integer
              placeholder="days"
              value={schedule.every}
              onChange={(v) => onChange({ ...schedule, every: Math.max(1, v || 1) })}
            />
          )}
          <input
            className="in"
            type="date"
            aria-label="Next date"
            value={schedule.next}
            min={tomorrow}
            onChange={(e) => onChange({ ...schedule, next: e.target.value })}
          />
        </>
      )}
    </div>
  );
}
