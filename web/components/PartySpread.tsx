"use client";

import { useMemo, useState } from "react";
import type { Score } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { fmtScore } from "@/lib/viz";

const W = 720;
const PAD_L = 36;
const PAD_R = 36;
const PAD_T = 28;
const LANE_H = 56;
const PAD_B = 36;

function beeswarm(
  values: { id: string; v: number; score: Score }[],
  xOf: (v: number) => number,
  cy: number,
  radius = 7,
): { id: string; x: number; y: number; score: Score }[] {
  const placed: { id: string; x: number; y: number; score: Score; r: number }[] = [];
  const sorted = [...values].sort((a, b) => a.v - b.v);
  for (const item of sorted) {
    const x = xOf(item.v);
    let y = cy;
    let guard = 0;
    while (guard++ < 40) {
      const hit = placed.some((p) => {
        const dx = p.x - x;
        const dy = p.y - y;
        return Math.hypot(dx, dy) < p.r + radius - 0.5;
      });
      if (!hit) break;
      const step = Math.ceil(guard / 2) * (radius * 1.55);
      y = cy + (guard % 2 === 0 ? step : -step);
    }
    placed.push({ id: item.id, x, y, score: item.score, r: radius });
  }
  return placed;
}

export default function PartySpread({
  rows,
  theme,
  flagged,
  focusId,
  selectedId,
  onHover,
  onSelect,
}: {
  rows: Score[];
  theme: string;
  flagged: Set<string>;
  focusId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const [tip, setTip] = useState<{ score: Score; x: number; y: number } | null>(null);
  const active = focusId ?? selectedId;

  const layout = useMemo(() => {
    const dem = rows.filter((r) => r.party === "Democrat");
    const rep = rows.filter((r) => r.party === "Republican");
    const H = PAD_T + LANE_H * 2 + PAD_B + 20;
    const x = (v: number) =>
      PAD_L + ((Math.max(-1, Math.min(1, v)) + 1) / 2) * (W - PAD_L - PAD_R);

    const demPts = beeswarm(
      dem.map((s) => ({ id: s.bioguide_id, v: s.signed_score, score: s })),
      x,
      PAD_T + LANE_H * 0.55,
    );
    const repPts = beeswarm(
      rep.map((s) => ({ id: s.bioguide_id, v: s.signed_score, score: s })),
      x,
      PAD_T + LANE_H + LANE_H * 0.55,
    );
    return { H, x, demPts, repPts };
  }, [rows]);

  if (!rows.length) {
    return <p className="cap">No sufficient members for a party spread in this filter.</p>;
  }

  const ticks = [-1, -0.5, 0, 0.5, 1];

  return (
    <div className="viz-frame">
      <svg
        viewBox={`0 0 ${W} ${layout.H}`}
        width="100%"
        role="img"
        aria-label={`Party spread of signed scores for ${themeLabel(theme)}`}
      >
        <rect
          x={PAD_L}
          y={PAD_T}
          width={W - PAD_L - PAD_R}
          height={LANE_H * 2}
          fill="var(--paper)"
          stroke="var(--line)"
        />
        <line
          x1={PAD_L}
          y1={PAD_T + LANE_H}
          x2={W - PAD_R}
          y2={PAD_T + LANE_H}
          stroke="var(--line-strong)"
          strokeWidth={1}
        />

        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={layout.x(t)}
              y1={PAD_T}
              x2={layout.x(t)}
              y2={PAD_T + LANE_H * 2}
              stroke={t === 0 ? "var(--navy)" : "var(--line)"}
              strokeWidth={t === 0 ? 1.3 : 1}
              strokeDasharray={t === 0 ? undefined : "2 4"}
              opacity={t === 0 ? 0.45 : 1}
            />
            <text
              x={layout.x(t)}
              y={PAD_T + LANE_H * 2 + 16}
              textAnchor="middle"
              fontSize={10.5}
              fill="var(--ink3)"
              fontWeight={t === 0 ? 600 : 400}
            >
              {t > 0 ? "+" : ""}
              {t}
            </text>
          </g>
        ))}

        <text x={10} y={PAD_T + LANE_H * 0.55 + 4} fontSize={11} fontWeight={700} fill="var(--dem)">
          Dem
        </text>
        <text
          x={10}
          y={PAD_T + LANE_H + LANE_H * 0.55 + 4}
          fontSize={11}
          fontWeight={700}
          fill="var(--rep)"
        >
          Rep
        </text>

        {[...layout.demPts, ...layout.repPts].map((p) => {
          const isFlag = flagged.has(p.score.bioguide_id);
          const isActive = active === p.id;
          const isSelected = selectedId === p.id;
          const color = isFlag
            ? "var(--flag)"
            : p.score.party === "Democrat"
              ? "var(--dem)"
              : "var(--rep)";
          return (
            <circle
              key={p.id}
              cx={p.x}
              cy={p.y}
              r={isActive ? 9.5 : isFlag ? 8 : 6.5}
              fill={color}
              stroke={isSelected ? "var(--navy)" : "var(--surface)"}
              strokeWidth={isSelected ? 2.6 : 1.6}
              opacity={active != null && !isActive ? 0.2 : 0.95}
              className="viz-hit"
              style={{ cursor: "pointer" }}
              onMouseEnter={(e) => {
                onHover(p.id);
                setTip({ score: p.score, x: e.clientX, y: e.clientY });
              }}
              onMouseMove={(e) => setTip({ score: p.score, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => {
                onHover(null);
                setTip(null);
              }}
              onClick={() => onSelect(p.id)}
            />
          );
        })}
      </svg>
      <p className="scale-cap">
        {themeLabel(theme)} · hover to link with the forest plot · click to select. Gold = crossed
        caucus.
      </p>
      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          <strong>
            {shortName(tip.score.full_name)} · {fmtScore(tip.score.signed_score)}
          </strong>
          Wilson [{fmtScore(tip.score.wilson_low)}, {fmtScore(tip.score.wilson_high)}]
          <br />
          {tip.score.n_yea}Y / {tip.score.n_nay}N · n={tip.score.n_contested}
        </div>
      )}
    </div>
  );
}
