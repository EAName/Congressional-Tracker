"use client";

import { useMemo, useState } from "react";
import type { IrtDoc, IrtMember, Member } from "@/lib/types";
import { shortName } from "@/lib/types";

const W = 760;
const PAD_L = 178;
const PAD_R = 108;
const PAD_T = 22;
const ROW_H = 36;
const PAD_B = 36;

const partyColor = (p: string | null, target: boolean) => {
  if (target) return "var(--flag)";
  if (p === "Democrat") return "var(--dem)";
  if (p === "Republican") return "var(--rep)";
  return "var(--ink3)";
};

export default function IdealPoints({
  irt,
  delegation,
  focusId,
  selectedId,
  onHover,
  onSelect,
}: {
  irt: IrtDoc;
  delegation: Member[];
  focusId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const [tip, setTip] = useState<{ row: IrtMember; x: number; y: number } | null>(null);
  const targets = useMemo(
    () => new Set(delegation.filter((m) => m.is_target).map((m) => m.bioguide_id)),
    [delegation],
  );
  const sorted = useMemo(
    () => [...irt.members].sort((a, b) => a.theta_mean - b.theta_mean),
    [irt.members],
  );
  const lo = Math.min(...sorted.map((r) => r.theta_hdi_lo), -1);
  const hi = Math.max(...sorted.map((r) => r.theta_hdi_hi), 1);
  const span = hi - lo || 1;
  const x = (v: number) => PAD_L + ((v - lo) / span) * (W - PAD_L - PAD_R);
  const H = PAD_T + sorted.length * ROW_H + PAD_B;
  const active = focusId ?? selectedId;
  const ticks = [lo, 0, hi].filter((t, i, a) => a.findIndex((x) => Math.abs(x - t) < 1e-6) === i);
  const lowName = sorted.find((m) => m.is_anchor_low);
  const highName = sorted.find((m) => m.is_anchor_high);

  if (sorted.length === 0) {
    return <p className="cap">No IRT artifact. Run `make irt` after installing the irt extra.</p>;
  }

  return (
    <div className="plot-frame">
      <div className="plot">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          aria-label="One-dimensional IRT ideal points with 95% highest-density intervals"
        >
          <text x={PAD_L} y={12} fontSize={9.5} fill="var(--ink3)" textAnchor="start">
            {lowName ? shortName(lowName.full_name) : "low anchor"} pole
          </text>
          <text x={W - PAD_R} y={12} fontSize={9.5} fill="var(--ink3)" textAnchor="end">
            {highName ? shortName(highName.full_name) : "high anchor"} pole
          </text>
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={x(t)}
                y1={PAD_T}
                x2={x(t)}
                y2={H - PAD_B}
                stroke={Math.abs(t) < 1e-6 ? "var(--navy)" : "var(--line)"}
                strokeWidth={Math.abs(t) < 1e-6 ? 1.4 : 1}
                strokeDasharray={Math.abs(t) < 1e-6 ? undefined : "2 4"}
                opacity={Math.abs(t) < 1e-6 ? 0.55 : 1}
              />
              <text x={x(t)} y={H - PAD_B + 16} textAnchor="middle" fontSize={10.5} fill="var(--ink3)">
                {t.toFixed(1)}
              </text>
            </g>
          ))}
          {sorted.map((r, i) => {
            const cy = PAD_T + i * ROW_H + ROW_H / 2;
            const isTarget = targets.has(r.bioguide_id);
            const isActive = active === r.bioguide_id;
            const isSelected = selectedId === r.bioguide_id;
            const color = partyColor(r.party, isTarget);
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
                {(isTarget || isSelected) && (
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
                  {r.district_number ? `VA-${r.district_number}` : r.chamber}
                  {r.is_anchor_low || r.is_anchor_high ? " · anchor" : ""}
                  {isTarget ? " · target" : ""}
                </text>
                <line
                  x1={x(r.theta_hdi_lo)}
                  y1={cy}
                  x2={x(r.theta_hdi_hi)}
                  y2={cy}
                  stroke={color}
                  strokeWidth={isActive ? 4 : 3}
                  strokeLinecap="round"
                  opacity={0.35}
                />
                <circle
                  cx={x(r.theta_mean)}
                  cy={cy}
                  r={isActive ? 8 : 5.8}
                  fill={color}
                  stroke={isSelected ? "var(--navy)" : isTarget ? "var(--flag)" : "var(--surface)"}
                  strokeWidth={isSelected || isTarget ? 2.4 : 1.8}
                />
              </g>
            );
          })}
        </svg>
      </div>
      <p className="scale-cap">
        2PL on raw YEA/NAY (all themes). Sign pinned so {highName ? shortName(highName.full_name) : "high"} sits
        to the right of {lowName ? shortName(lowName.full_name) : "low"}. Gold stroke = target seat. R-hat max{" "}
        {irt.diagnostics.rhat_max}.
      </p>
      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          <strong>{shortName(tip.row.full_name)}</strong>
          <br />
          θ {tip.row.theta_mean.toFixed(2)} [{tip.row.theta_hdi_lo.toFixed(2)}, {tip.row.theta_hdi_hi.toFixed(2)}]
        </div>
      )}
    </div>
  );
}
