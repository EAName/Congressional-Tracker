"use client";

import { useMemo, useState } from "react";
import type { Score, ScoreMode } from "@/lib/types";
import { shortName } from "@/lib/types";
import { clampTickX, scoreTickLabel, tickAnchorAtIndex } from "@/lib/chart-axis";
import { estimate, fmtScore } from "@/lib/viz";

const W = 680;
const H = 168;
const PAD_L = 150;
const PAD_R = 40;
const PAD_T = 28;
const PAD_B = 36;
const ROW = 44;

export default function CompareOverlay({
  rows,
  memberA,
  memberB,
  onChangeA,
  onChangeB,
  mode = "eb",
}: {
  rows: Score[];
  memberA: string | null;
  memberB: string | null;
  onChangeA: (id: string | null) => void;
  onChangeB: (id: string | null) => void;
  mode?: ScoreMode;
}) {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

  const options = useMemo(
    () =>
      [...rows].sort(
        (a, b) =>
          (a.district_number ?? 100) - (b.district_number ?? 100) ||
          a.full_name.localeCompare(b.full_name),
      ),
    [rows],
  );

  const a = rows.find((r) => r.bioguide_id === memberA) ?? null;
  const b = rows.find((r) => r.bioguide_id === memberB) ?? null;
  const aEst = a ? estimate(a, mode) : null;
  const bEst = b ? estimate(b, mode) : null;

  const x = (v: number) =>
    PAD_L + ((Math.max(-1, Math.min(1, v)) + 1) / 2) * (W - PAD_L - PAD_R);

  const delta = aEst && bEst ? aEst.value - bEst.value : null;
  const overlap =
    aEst && bEst ? !(aEst.hi < bEst.lo || bEst.hi < aEst.lo) : null;

  const colorFor = (s: Score) =>
    s.party === "Democrat" ? "var(--dem)" : s.party === "Republican" ? "var(--rep)" : "var(--ink3)";
  const ticks = [-1, -0.5, 0, 0.5, 1];
  const tickBounds = { min: PAD_L + 4, max: W - PAD_R - 4 };

  const renderRow = (s: Score, idx: number) => {
    const est = estimate(s, mode);
    if (!est) return null;
    const cy = PAD_T + idx * ROW + ROW / 2;
    const color = colorFor(s);
    const band = est.kind === "credible" ? "Cred" : "Wilson";
    return (
      <g
        key={s.bioguide_id}
        onMouseEnter={(e) =>
          setTip({
            text: `${shortName(s.full_name)} · ${fmtScore(est.value)} · ${band} [${fmtScore(est.lo)}, ${fmtScore(est.hi)}] · n=${est.n}`,
            x: e.clientX,
            y: e.clientY,
          })
        }
        onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
        onMouseLeave={() => setTip(null)}
      >
        <text x={12} y={cy - 2} fontSize={12.5} fontWeight={650} fill={color}>
          {shortName(s.full_name)}
        </text>
        <text x={12} y={cy + 12} fontSize={10} fill="var(--ink3)">
          {s.district_number != null ? `VA-${s.district_number}` : s.chamber} · n={est.n}
        </text>
        <line
          x1={x(est.lo)}
          y1={cy}
          x2={x(est.hi)}
          y2={cy}
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          opacity={0.28}
        />
        <line
          x1={x(est.lo)}
          y1={cy - 7}
          x2={x(est.lo)}
          y2={cy + 7}
          stroke={color}
          strokeWidth={2}
        />
        <line
          x1={x(est.hi)}
          y1={cy - 7}
          x2={x(est.hi)}
          y2={cy + 7}
          stroke={color}
          strokeWidth={2}
        />
        <circle
          cx={x(est.value)}
          cy={cy}
          r={7}
          fill={color}
          stroke="var(--bg-elev)"
          strokeWidth={2}
        />
      </g>
    );
  };

  return (
    <div>
      <div className="compare-pickers">
        <div className="compare-field">
          <label htmlFor="compare-a">Member A</label>
          <select
            id="compare-a"
            value={memberA ?? ""}
            onChange={(e) => onChangeA(e.target.value || null)}
          >
            <option value="">Select…</option>
            {options.map((r) => (
              <option key={r.bioguide_id} value={r.bioguide_id} disabled={r.bioguide_id === memberB}>
                {shortName(r.full_name)}
                {r.district_number != null ? ` (VA-${r.district_number})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="compare-field">
          <label htmlFor="compare-b">Member B</label>
          <select
            id="compare-b"
            value={memberB ?? ""}
            onChange={(e) => onChangeB(e.target.value || null)}
          >
            <option value="">Select…</option>
            {options.map((r) => (
              <option key={r.bioguide_id} value={r.bioguide_id} disabled={r.bioguide_id === memberA}>
                {shortName(r.full_name)}
                {r.district_number != null ? ` (VA-${r.district_number})` : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!a && !b ? (
        <p className="cap">Pin two members with sufficient scores in this theme to overlay intervals.</p>
      ) : (
        <>
          <div className="viz-frame" style={{ position: "relative" }}>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Compare score intervals">
              <line
                x1={x(0)}
                y1={PAD_T - 8}
                x2={x(0)}
                y2={H - PAD_B + 8}
                stroke="var(--zero)"
                strokeWidth={1.4}
                opacity={0.7}
              />
              {ticks.map((t, i) => {
                const anchor = tickAnchorAtIndex(i, ticks.length);
                return (
                  <text
                    key={t}
                    x={clampTickX(x(t), tickBounds, anchor)}
                    y={H - 12}
                    textAnchor={anchor}
                    fontSize={10}
                    fill="var(--ink3)"
                  >
                    {scoreTickLabel(t)}
                  </text>
                );
              })}
              {a && renderRow(a, 0)}
              {b && renderRow(b, 1)}
            </svg>
            {tip && (
              <div className="tooltip" style={{ left: tip.x, top: tip.y, whiteSpace: "normal" }}>
                {tip.text}
              </div>
            )}
          </div>

          <div className="compare-stats">
            <div className="compare-stat">
              <p className="k">Score delta (A − B)</p>
              <p className="v">
                {delta == null ? "—" : fmtScore(delta)}
              </p>
            </div>
            <div className="compare-stat">
              <p className="k">{mode === "eb" ? "Credible intervals" : "Wilson intervals"}</p>
              <p className={`v ${overlap == null ? "" : overlap ? "warn" : "ok"}`}>
                {overlap == null ? "—" : overlap ? "Overlap" : "Separated"}
              </p>
            </div>
            <div className="compare-stat">
              <p className="k">Evidence (n)</p>
              <p className="v">
                {a && b ? `${a.n_contested} vs ${b.n_contested}` : "—"}
              </p>
            </div>
          </div>
          <p className="scale-cap">
            Separated intervals are stronger evidence of a real gap at this theme; overlap means
            uncertainty bands still touch given current vote depth.
          </p>
        </>
      )}
    </div>
  );
}
