"use client";

import { useMemo } from "react";
import type { TimePoint, TimeSeriesCell } from "@/lib/types";
import { clampTickX, timeAxisTicks } from "@/lib/chart-axis";
import { fmtScore } from "@/lib/viz";

const W = 720;
const H = 260;
const PAD_L = 44;
const PAD_R = 48;
const PAD_T = 16;
const PAD_B = 36;
const MIN_TICK_GAP_PX = 72;

function xOf(dates: string[], d: string): number {
  const inner = W - PAD_L - PAD_R;
  if (dates.length === 1) return PAD_L + inner / 2;
  const t0 = Date.parse(dates[0]);
  const t1 = Date.parse(dates[dates.length - 1]);
  if (t1 === t0) return PAD_L + inner / 2;
  return PAD_L + ((Date.parse(d) - t0) / (t1 - t0)) * inner;
}

function yOf(v: number): number {
  const inner = H - PAD_T - PAD_B;
  const clamped = Math.max(-1, Math.min(1, v));
  return PAD_T + ((1 - clamped) / 2) * inner;
}

function bandPath(points: TimePoint[], dates: string[]): string {
  if (points.length === 0) return "";
  const top = points.map((p) => `${xOf(dates, p.date).toFixed(1)},${yOf(p.hi).toFixed(1)}`);
  const bot = [...points]
    .reverse()
    .map((p) => `${xOf(dates, p.date).toFixed(1)},${yOf(p.lo).toFixed(1)}`);
  return `M${top[0]} L${top.slice(1).join(" L")} L${bot.join(" L")} Z`;
}

function linePath(points: TimePoint[], dates: string[]): string {
  return points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xOf(dates, p.date).toFixed(1)},${yOf(p.eb).toFixed(1)}`)
    .join(" ");
}

export default function ScoreOverTime({
  cell,
  selectedId,
  themeLabel: themeName,
}: {
  cell: TimeSeriesCell | null;
  selectedId: string | null;
  themeLabel: string;
}) {
  const points = cell?.points ?? [];
  const dates = useMemo(() => points.map((p) => p.date), [points]);
  const xTicks = useMemo(
    () => timeAxisTicks(dates, (d) => xOf(dates, d), MIN_TICK_GAP_PX),
    [dates],
  );
  const last = points[points.length - 1];
  const first = points[0];
  const color = cell?.party === "Republican" ? "var(--rep)" : "var(--dem)";
  const tickBounds = { min: PAD_L + 2, max: W - PAD_R - 2 };

  if (!selectedId) {
    return <p className="cap">Select a member on the forest, strip, or compare to plot their expanding-window score.</p>;
  }
  if (!cell || points.length === 0) {
    return (
      <p className="cap">
        No contested votes for this member on {themeName}. Switch theme or pick another member.
      </p>
    );
  }

  const narrowed = last && first ? last.hi - last.lo < first.hi - first.lo : false;

  return (
    <div className="time-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Score over time for ${cell.full_name}`}>
        {[-1, -0.5, 0, 0.5, 1].map((t) => (
          <g key={t}>
            <line
              x1={PAD_L}
              y1={yOf(t)}
              x2={W - PAD_R}
              y2={yOf(t)}
              stroke={t === 0 ? "var(--line-strong)" : "var(--line)"}
              strokeDasharray={t === 0 ? "0" : "3 4"}
            />
            <text x={PAD_L - 8} y={yOf(t) + 3} textAnchor="end" fontSize={10} fill="var(--ink3)">
              {t > 0 ? `+${t}` : t}
            </text>
          </g>
        ))}
        <path d={bandPath(points, dates)} fill={color} opacity={0.18} />
        <path d={linePath(points, dates)} fill="none" stroke={color} strokeWidth={2} />
        {points.map((p) => (
          <circle key={p.date} cx={xOf(dates, p.date)} cy={yOf(p.eb)} r={2.6} fill={color} />
        ))}
        {xTicks.map(({ date, label, anchor }) => (
          <text
            key={`${date}-${anchor}`}
            x={clampTickX(xOf(dates, date), tickBounds, anchor)}
            y={H - 10}
            textAnchor={anchor}
            fontSize={10}
            fill="var(--ink3)"
          >
            {label}
          </text>
        ))}
      </svg>
      <p className="scale-cap">
        {cell.full_name} · n {first.n}→{last.n}
        {narrowed ? " · band narrowed as votes accumulated" : " · band width tracks n and the as-of caucus prior"}
        {" · last "}
        {fmtScore(last.eb)} [{fmtScore(last.lo)}, {fmtScore(last.hi)}]
      </p>
    </div>
  );
}
