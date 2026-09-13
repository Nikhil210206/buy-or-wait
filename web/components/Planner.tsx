"use client";

import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import ScenarioForm from "./ScenarioForm";
import Verdict from "./Verdict";
import { solve } from "@/lib/engine";
import { STATUS, money } from "@/lib/format";
import { type Scenario, blankScenario, todayIso } from "@/lib/scenario";
import type { Preset } from "@/lib/types";

const STORE = "buy-or-wait:v1";

function encode(s: Scenario) {
  let bin = "";
  for (const b of new TextEncoder().encode(JSON.stringify(s))) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decode(str: string): Scenario | null {
  try {
    const bin = atob(str.replace(/-/g, "+").replace(/_/g, "/"));
    const s = JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
    return s?.version === 1 ? s : null;
  } catch {
    return null;
  }
}

export type Edit = (fn: (draft: Scenario) => void) => void;

export default function Planner({ presets }: { presets: Preset[] }) {
  const [scenario, setScenario] = useState<Scenario>(presets[0]?.scenario ?? blankScenario("2026-01-01"));
  const [presetId, setPresetId] = useState<string | null>(presets[0]?.id ?? null);
  const [toast, setToast] = useState<string | null>(null);
  const loaded = useRef(false);
  const verdictRef = useRef<HTMLDivElement>(null);

  // Restore a shared link or the last session once, on the client.
  useEffect(() => {
    queueMicrotask(() => {
      const shared = window.location.hash.startsWith("#s=") ? decode(window.location.hash.slice(3)) : null;
      if (shared) {
        setScenario(shared);
        setPresetId(null);
        history.replaceState(null, "", window.location.pathname);
      } else {
        try {
          const saved = JSON.parse(localStorage.getItem(STORE) ?? "null");
          if (saved?.scenario?.version === 1) {
            setScenario(saved.scenario);
            setPresetId(saved.presetId ?? null);
          }
        } catch {
          /* storage unavailable: keep the example */
        }
      }
      loaded.current = true;
    });
  }, []);

  useEffect(() => {
    if (!loaded.current) return;
    try {
      localStorage.setItem(STORE, JSON.stringify({ scenario, presetId }));
    } catch {
      /* private mode or quota: nothing to do */
    }
  }, [scenario, presetId]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  const edit: Edit = useCallback((fn) => {
    setScenario((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  }, []);

  const deferred = useDeferredValue(scenario);
  const decision = useMemo(() => solve(deferred), [deferred]);
  const preset = presets.find((p) => p.id === presetId);

  function share() {
    const url = `${window.location.origin}${window.location.pathname}#s=${encode(scenario)}`;
    navigator.clipboard.writeText(url).then(
      () => setToast("Link copied. Anyone with it sees this scenario."),
      () => setToast("Could not copy the link."),
    );
  }

  return (
    <div className="planner">
      <div className="toolbar">
        <span className="eyebrow">Try an example</span>
        {presets.map((p) => (
          <button
            key={p.id}
            className="chip"
            aria-pressed={presetId === p.id}
            onClick={() => {
              setScenario(structuredClone(p.scenario));
              setPresetId(p.id);
            }}
          >
            {p.title}
            <small>{STATUS[solve(p.scenario).status].label}</small>
          </button>
        ))}
        <span className="toolbar-sep" />
        <button
          className="chip chip-ghost"
          onClick={() => {
            setScenario({ ...blankScenario(todayIso()), currency: scenario.currency });
            setPresetId(null);
          }}
        >
          Start blank
        </button>
        <button className="chip chip-ghost" onClick={share}>
          Share link
        </button>
      </div>
      {preset && (
        <p className="example-note">
          Example from the test set: &ldquo;{preset.question}&rdquo; Edit anything to make it yours.
        </p>
      )}

      <div className="planner-grid">
        <ScenarioForm scenario={scenario} edit={edit} replace={setScenario} />
        <div className="verdict-col" ref={verdictRef}>
          <Verdict scenario={deferred} decision={decision} stale={deferred !== scenario} />
        </div>
      </div>

      {scenario.request.amount > 0 && (
        <button className="mobile-bar" onClick={() => verdictRef.current?.scrollIntoView({ behavior: "smooth" })}>
          <b style={{ color: "var(--paper-solid)" }}>{STATUS[decision.status].word}</b>
          <span>
            {STATUS[decision.status].tail} · safe today {money(decision.safeToday, scenario.currency)}
          </span>
          <span aria-hidden>↓</span>
        </button>
      )}
      {toast && (
        <div role="status" className="toast">
          {toast}
        </div>
      )}
    </div>
  );
}
