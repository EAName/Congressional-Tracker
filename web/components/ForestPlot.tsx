"use client";

import { useId, useMemo, useState } from "react";
import type { Score, ScoreMode } from "@/lib/types";
import { shortName } from "@/lib/types";
import { estimate, fmtScore } from "@/lib/viz";

const W = 760;
const PAD_L = 178;
const PAD_R = 108;
const PAD_T = 18;
const ROW_H = 36;
const PAD_B = 36;

const partyColor = (p: string | null, flagged: boolean) => {
  if (flagged) return "var(--flag)";
  if (p === "Democrat") return "var(--dem)";
  if (p === "Republican") return "var(--rep)";
  return "var(--ink3)";
};

interface Tip {
  row: Score;
  x: number;
  y: number;
}

export default function ForestPlot({
  rows,
  flagged,
  focusId,
  selectedId,
  onHover,
  onSelect,
  partyBaselines,
  mode = "eb",
}: {
  rows: Score[];
  flagged: Set<string>;
  focusId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  partyBaselines?: { Democrat?: number; Republican?: number };
  mode?: ScoreMode;
}) {
  const gid = useId().replace(/:/g, "");
  const [tip, setTip] = useState<Tip | null>(null);

  const sorted = useMemo(() => {
    const withEst = rows
      .map((r) => ({ row: r, est: estimate(r, mode) }))
      .filter((x): x is { row: Score; est: NonNullable<ReturnType<typeof estimate>> } => x.est != null);
    withEst.sort(
      (a, b) => b.est.value - a.est.value || a.row.full_name.localeCompare(b.row.full_name),
    );
    return withEst;
  }, [rows, mode]);

  const H = PAD_T + sorted.length * ROW_H + PAD_B;
  const x = (v: number) => PAD_L + ((Math.max(-1, Math.min(1, v)) + 1) / 2) * (W - PAD_L - PAD_R);
  const ticks = [-1, -0.5, 0, 0.5, 1];
  const active = focusId ?? selectedId;

  return (
    <div className="plot-frame">
      <div className="plot">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          aria-label={`Forest plot of ${sorted.length} members' ${mode === "eb" ? "empirical Bayes" : "raw"} scores`}
        >
          <defs>
            <linearGradient id={`axis-${gid}`} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="var(--rep)" stopOpacity="0.12" />
              <stop offset="50%" stopColor="var(--zero)" stopOpacity="0.04" />
              <stop offset="100%" stopColor="var(--dem)" stopOpacity="0.12" />
            </linearGradient>
          </defs>

          <rect
            x={PAD_L}
            y={PAD_T}
            width={W - PAD_L - PAD_R}
            height={Math.max(0, H - PAD_T - PAD_B)}
            fill={`url(#axis-${gid})`}
          />

          <text x={PAD_L} y={12} fontSize={9.5} fill="var(--ink3)" textAnchor="start">
            opposed axis
          </text>
          <text x={W - PAD_R} y={12} fontSize={9.5} fill="var(--ink3)" textAnchor="end">
            advanced axis
          </text>

          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={x(t)}
                y1={PAD_T}
                x2={x(t)}
                y2={H - PAD_B}
                stroke={t === 0 ? "var(--navy)" : "var(--line)"}
                strokeWidth={t === 0 ? 1.4 : 1}
                strokeDasharray={t === 0 ? undefined : "2 4"}
                opacity={t === 0 ? 0.55 : 1}
              />
              <text
                x={x(t)}
                y={H - PAD_B + 16}
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

          {partyBaselines?.Democrat != null && (
            <line
              x1={x(partyBaselines.Democrat)}
              y1={PAD_T}
              x2={x(partyBaselines.Democrat)}
              y2={H - PAD_B}
              stroke="var(--dem)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              opacity={0.55}
            />
          )}
          {partyBaselines?.Republican != null && (
            <line
              x1={x(partyBaselines.Republican)}
              y1={PAD_T}
              x2={x(partyBaselines.Republican)}
              y2={H - PAD_B}
              stroke="var(--rep)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              opacity={0.55}
            />
          )}

          {sorted.map(({ row: r, est }, i) => {
            const cy = PAD_T + i * ROW_H + ROW_H / 2;
            const isFlagged = flagged.has(r.bioguide_id);
            const isActive = active === r.bioguide_id;
            const isSelected = selectedId === r.bioguide_id;
            const color = partyColor(r.party, isFlagged);
            const dim = active != null && !isActive;
            return (
              <g
                key={r.bioguide_id}
                className="viz-hit"
                opacity={dim ? 0.22 : 1}
                style={{ cursor: "pointer" }}
                onMouseEnter={(e) => {
                  onHover(r.bioguide_id);
                  setTip({ row: r, x: e.clientX, y: e.clientY });
                }}
                onMouseMove={(e) => setTip({ row: r, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => {
                  onHover(null);
                  setTip(null);
                }}
                onClick={() => onSelect(r.bioguide_id)}
              >
                {(isFlagged || isSelected) && (
                  <rect
                    x={4}
                    y={cy - ROW_H / 2 + 2}
                    width={W - 8}
                    height={ROW_H - 4}
                    rx={3}
                    fill={isSelected ? "var(--dem-soft)" : "var(--flag-soft)"}
                    opacity={0.9}
                  />
                )}
                <text x={14} y={cy - 2} fontSize={13} fontWeight={600} fill="var(--ink)">
                  {shortName(r.full_name)}
                </text>
                <text x={14} y={cy + 12} fontSize={10.5} fill="var(--ink3)">
                  {r.district_number ? `VA-${r.district_number}` : r.chamber} · n={est.n}
                </text>
                <line
                  x1={x(est.lo)}
                  y1={cy}
                  x2={x(est.hi)}
                  y2={cy}
                  stroke={color}
                  strokeWidth={isActive ? 4 : 3}
                  strokeLinecap="round"
                  opacity={0.35}
                />
                <line
                  x1={x(est.lo)}
                  y1={cy - 4}
                  x2={x(est.lo)}
                  y2={cy + 4}
                  stroke={color}
                  strokeWidth={1.6}
                  opacity={0.7}
                />
                <line
                  x1={x(est.hi)}
                  y1={cy - 4}
                  x2={x(est.hi)}
                  y2={cy + 4}
                  stroke={color}
                  strokeWidth={1.6}
                  opacity={0.7}
                />
                <circle
                  cx={x(est.value)}
                  cy={cy}
                  r={isActive ? 8 : 5.8}
                  fill={color}
                  stroke={isSelected ? "var(--navy)" : "var(--surface)"}
                  strokeWidth={isSelected ? 2.4 : 1.8}
                />
                {isFlagged && (
                  <text
                    x={W - 12}
                    y={cy + 4}
                    textAnchor="end"
                    fontSize={10}
                    fontWeight={600}
                    fill="var(--flag)"
                  >
                    crossed caucus →
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {tip && (() => {
          const est = estimate(tip.row, mode);
          if (!est) return null;
          const band = est.kind === "credible" ? "Cred" : "Wilson";
          return (
            <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
              <strong>
                {shortName(tip.row.full_name)} · {fmtScore(est.value)}
              </strong>
              {band} [{fmtScore(est.lo)}, {fmtScore(est.hi)}]
              <br />
              k={est.k} / n={est.n} · click to focus
              {flagged.has(tip.row.bioguide_id) ? " · opens defections" : ""}
            </div>
          );
        })()}
      </div>
    </div>
  );
}
