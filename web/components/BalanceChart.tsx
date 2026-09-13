"use client";

import { useMemo, useState } from "react";
import { addDays, compact, daysBetween, money, shortDate } from "@/lib/format";

type Props = {
  start: string;
  base: number[];
  withPlan: number[];
  floor: number;
  plan: { date: string; amount: number }[];
  currency: string;
  planDiffers: boolean;
};

const W = 880;
const H = 330;
const P = { l: 58, r: 18, t: 22, b: 34 };

export default function BalanceChart({ start, base, withPlan, floor, plan, currency, planDiffers }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const n = withPlan.length;

  const { lo, hi } = useMemo(() => {
    const all = [...base, ...withPlan, floor];
    const mn = Math.min(...all);
    const mx = Math.max(...all);
    const pad = (mx - mn) * 0.1 || Math.abs(mx) * 0.1 || 1;
    return { lo: mn - pad, hi: mx + pad };
  }, [base, withPlan, floor]);

  const x = (i: number) => P.l + (i / (n - 1)) * (W - P.l - P.r);
  const y = (v: number) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
  const step = (arr: number[]) =>
    arr.map((v, i) => (i === 0 ? `M${x(0)},${y(v)}` : `H${x(i)}V${y(v)}`)).join("");

  const low = withPlan.reduce((best, v, i) => (v < withPlan[best] ? i : best), 0);
  const floorY = y(floor);
  const ticksX = Array.from({ length: Math.floor((n - 1) / 15) + 1 }, (_, k) => k * 15);
  const ticksY = Array.from({ length: 5 }, (_, k) => lo + ((hi - lo) * (k + 0.5)) / 5);

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((sx - P.l) / (W - P.l - P.r)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  }

  const tipLeft = hover !== null && x(hover) > W * 0.62;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="chart"
      role="img"
      aria-label={`Projected balance over ${n - 1} days, lowest ${money(withPlan[low], currency)}`}
      onPointerMove={onMove}
      onPointerLeave={() => setHover(null)}
    >
      <defs>
        <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="7" stroke="var(--no)" strokeWidth="1" opacity="0.28" />
        </pattern>
        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--ink)" stopOpacity="0.09" />
          <stop offset="1" stopColor="var(--ink)" stopOpacity="0" />
        </linearGradient>
      </defs>

      {ticksY.map((v) => (
        <g key={v}>
          <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="chart-grid" />
          <text x={P.l - 10} y={y(v)} className="chart-axis" textAnchor="end" dominantBaseline="middle">
            {compact(v)}
          </text>
        </g>
      ))}
      {ticksX.map((i) => (
        <text key={i} x={x(i)} y={H - 10} className="chart-axis" textAnchor="middle">
          {i === 0 ? "Today" : shortDate(addDays(start, i))}
        </text>
      ))}

      {floorY < H - P.b && (
        <rect x={P.l} y={floorY} width={W - P.l - P.r} height={H - P.b - floorY} fill="url(#hatch)" />
      )}

      <path d={`${step(withPlan)}V${H - P.b}H${x(0)}Z`} fill="url(#fill)" />
      {planDiffers && <path d={step(base)} className="chart-base" />}
      <path d={step(withPlan)} className="chart-line" />

      <line x1={P.l} x2={W - P.r} y1={floorY} y2={floorY} className="chart-floor" />
      <text x={W - P.r} y={floorY - 7} className="chart-floor-label" textAnchor="end">
        Minimum {money(floor, currency)}
      </text>

      {plan.map((p) => {
        const i = daysBetween(start, p.date);
        if (i < 0 || i >= n) return null;
        return (
          <g key={p.date}>
            <line x1={x(i)} x2={x(i)} y1={P.t} y2={H - P.b} className="chart-pay" />
            <circle cx={x(i)} cy={y(withPlan[i])} r="4.5" className="chart-pay-dot" />
          </g>
        );
      })}

      <g>
        <circle cx={x(low)} cy={y(withPlan[low])} r="3" fill="var(--ink)" />
        <text
          x={x(low) + (low > n * 0.8 ? -8 : 8)}
          y={y(withPlan[low]) + 16}
          className="chart-note"
          textAnchor={low > n * 0.8 ? "end" : "start"}
        >
          low · {compact(withPlan[low])}
        </text>
      </g>

      {hover !== null && (
        <g pointerEvents="none">
          <line x1={x(hover)} x2={x(hover)} y1={P.t} y2={H - P.b} className="chart-cursor" />
          <circle cx={x(hover)} cy={y(withPlan[hover])} r="4" fill="var(--paper-solid)" stroke="var(--ink)" strokeWidth="1.5" />
          <g transform={`translate(${tipLeft ? x(hover) - 196 : x(hover) + 12}, ${P.t + 4})`}>
            <rect width="184" height={planDiffers ? 66 : 48} className="chart-tip" />
            <text x="12" y="19" className="chart-tip-date">
              {hover === 0 ? "Today" : `Day ${hover}`} · {shortDate(addDays(start, hover))}
            </text>
            <text x="12" y="38" className="chart-tip-val">
              {money(withPlan[hover], currency)}
            </text>
            {planDiffers && (
              <text x="12" y="56" className="chart-tip-sub">
                untouched {money(base[hover], currency)}
              </text>
            )}
          </g>
        </g>
      )}
    </svg>
  );
}
