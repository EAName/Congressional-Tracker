"use client";

import { useState } from "react";
import type { Score } from "@/lib/types";
import { shortName } from "@/lib/types";

const W = 680;
const PAD_L = 168;
const PAD_R = 92;
const PAD_T = 8;
const ROW_H = 30;
const PAD_B = 28;

const partyColor = (p: string | null) =>
  p === "Democrat" ? "var(--dem)" : p === "Republican" ? "var(--rep)" : "var(--ink3)";

const fmt = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);

interface Hover {
  row: Score;
  x: number;
  y: number;
}

export default function ForestPlot({
  rows,
  flagged,
  onSelect,
}: {
  rows: Score[];
  flagged: Set<string>;
  onSelect: (bioguide: string) => void;
}) {
  const [hover, setHover] = useState<Hover | null>(null);

  const sorted = [...rows].sort(
    (a, b) => b.signed_score - a.signed_score || a.full_name.localeCompare(b.full_name),
  );
  const H = PAD_T + sorted.length * ROW_H + PAD_B;
  const x = (v: number) => PAD_L + ((v + 1) / 2) * (W - PAD_L - PAD_R);
  const ticks = [-1, -0.5, 0, 0.5, 1];

  return (
    <div className="plot">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Forest plot of ${sorted.length} members' signed scores with confidence bands`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={x(t)}
              y1={PAD_T}
              x2={x(t)}
              y2={H - PAD_B}
              stroke={t === 0 ? "var(--zero)" : "var(--line)"}
              strokeWidth={t === 0 ? 1.5 : 1}
            />
            <text
              x={x(t)}
              y={H - PAD_B + 15}
              textAnchor="middle"
              fontSize={10.5}
              fill="var(--ink3)"
            >
              {t > 0 ? "+" : ""}
              {t}
            </text>
          </g>
        ))}

        {sorted.map((r, i) => {
          const cy = PAD_T + i * ROW_H + ROW_H / 2;
          const isFlagged = flagged.has(r.bioguide_id);
          const color = isFlagged ? "var(--flag)" : partyColor(r.party);
          return (
            <g
              key={r.bioguide_id}
              style={{ cursor: isFlagged ? "pointer" : "default" }}
              onMouseEnter={(e) => setHover({ row: r, x: e.clientX, y: e.clientY })}
              onMouseMove={(e) => setHover({ row: r, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)}
              onClick={() => isFlagged && onSelect(r.bioguide_id)}
            >
              {isFlagged && (
                <rect
                  x={0}
                  y={cy - ROW_H / 2}
                  width={W}
                  height={ROW_H}
                  rx={4}
                  fill="var(--flagbg)"
                />
              )}
              <text x={12} y={cy - 1} fontSize={12.5} fill="var(--ink)">
                {shortName(r.full_name)}
              </text>
              <text x={12} y={cy + 11} fontSize={11} fill="var(--ink3)">
                {r.district_number ? `VA-${r.district_number}` : r.chamber} &middot; n=
                {r.n_contested}
              </text>
              <line
                x1={x(r.wilson_low)}
                y1={cy}
                x2={x(r.wilson_high)}
                y2={cy}
                stroke={color}
                strokeWidth={2.4}
                strokeLinecap="round"
                opacity={0.5}
              />
              <circle
                cx={x(r.signed_score)}
                cy={cy}
                r={hover?.row.bioguide_id === r.bioguide_id ? 7 : 5.5}
                fill={color}
                stroke="var(--surface)"
                strokeWidth={1.5}
              />
              {isFlagged && (
                <text
                  x={W - 8}
                  y={cy + 3.5}
                  textAnchor="end"
                  fontSize={10}
                  fontWeight={600}
                  fill="var(--flag)"
                >
                  crossed caucus &#8599;
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          {shortName(hover.row.full_name)} &middot; {fmt(hover.row.signed_score)}
          <br />
          band [{fmt(hover.row.wilson_low)}, {fmt(hover.row.wilson_high)}] &middot; {hover.row.n_yea}
          Y/{hover.row.n_nay}N
        </div>
      )}
    </div>
  );
}
