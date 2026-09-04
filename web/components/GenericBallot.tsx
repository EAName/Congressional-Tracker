"use client";

import { useMemo, useState } from "react";
import { clampTickX, separateLabelYs, tickAnchorAtIndex } from "@/lib/chart-axis";
import type { GenericBallotDoc, GenericBallotPoint } from "@/lib/types";

const W = 900;
const H = 420;
const PAD = { top: 24, right: 132, bottom: 40, left: 48 };

type Mode = "shares" | "margin";

function niceDateTicks(series: GenericBallotPoint[]) {
  const seen = new Map<string, number>();
  series.forEach((pt, i) => {
    const key = pt.date.slice(0, 7);
    if (!seen.has(key)) seen.set(key, i);
  });
  const months = [...seen.entries()];
  const step = Math.max(1, Math.ceil(months.length / 7));
  return months.filter((_, i) => i % step === 0);
}

function fmtMonth(iso: string) {
  const [y, m] = iso.split("-");
  const name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][
    Number(m) - 1
  ];
  return { name, year: y };
}

export default function GenericBallot({ doc }: { doc: GenericBallotDoc }) {
  const [mode, setMode] = useState<Mode>("shares");
  const gate = doc.environment_gate;

  const view = useMemo(() => {
    const s = doc.series;
    if (!s.length) return null;
    // Third-party share is carried by the headline split, so recover it once and
    // apply it across the series to keep the two lines on a headline basis.
    const cur = doc.current;
    const scale = cur ? cur.dem + cur.rep : 1;
    const rows = s.map((pt) => ({
      date: pt.date,
      dem: pt.dem_two_party * scale,
      rep: (1 - pt.dem_two_party) * scale,
      demLo: pt.lo * scale,
      demHi: pt.hi * scale,
      repLo: (1 - pt.hi) * scale,
      repHi: (1 - pt.lo) * scale,
    }));
    const lo = Math.min(...rows.map((r) => Math.min(r.demLo, r.repLo)));
    const hi = Math.max(...rows.map((r) => Math.max(r.demHi, r.repHi)));
    const pad = Math.max(0.02, (hi - lo) * 0.12);
    return { rows, yMin: Math.max(0, lo - pad), yMax: Math.min(1, hi + pad) };
  }, [doc]);

  if (!doc.series.length || !doc.current || !view) {
    return (
      <div className="gb-empty">
        <p className="cap">
          No average yet — the primary-poll archive holds {doc.n_polls} of the{" "}
          {doc.min_polls} polls required.
        </p>
        <p className="cap">
          Add rows to <code>data/generic_ballot_polls.csv</code> and re-run{" "}
          <code>vact export-web</code>. Aggregator output is not ingested, so this chart
          fills in as the archive is collected.
        </p>
      </div>
    );
  }

  const { rows, yMin, yMax } = view;
  const x = (i: number) => PAD.left + (i / Math.max(1, rows.length - 1)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);

  const line = (key: "dem" | "rep") =>
    rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`).join(" ");

  const band = (loKey: "demLo" | "repLo", hiKey: "demHi" | "repHi") => {
    const up = rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(r[hiKey]).toFixed(1)}`);
    const down = [...rows]
      .reverse()
      .map((r, i) => `L${x(rows.length - 1 - i).toFixed(1)},${y(r[loKey]).toFixed(1)}`);
    return `${up.join(" ")} ${down.join(" ")} Z`;
  };

  const ticks = niceDateTicks(doc.series);
  const tickBounds = { min: PAD.left + 4, max: W - PAD.right - 4 };
  const gridVals: number[] = [];
  const startTick = Math.ceil(yMin * 20) / 20;
  for (let v = startTick; v <= yMax + 1e-9; v += 0.05) gridVals.push(Number(v.toFixed(2)));

  const last = rows[rows.length - 1];
  const cur = doc.current;
  const leader = cur.margin_pp >= 0 ? "Democrats" : "Republicans";
  const [demLabelY, repLabelY] = separateLabelYs(y(last.dem), y(last.rep), 34);
  const demValueY = demLabelY + 22;
  const repValueY = repLabelY + 22;

  return (
    <div className="gb">
      <div className="gb-modes" role="tablist" aria-label="Generic ballot view">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "shares"}
          className={`gb-mode${mode === "shares" ? " is-active" : ""}`}
          onClick={() => setMode("shares")}
        >
          Generic ballot
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "margin"}
          className={`gb-mode${mode === "margin" ? " is-active" : ""}`}
          onClick={() => setMode("margin")}
        >
          Net support
        </button>
      </div>

      {mode === "shares" ? (
        <svg viewBox={`0 0 ${W} ${H}`} className="gb-svg" role="img"
             aria-label={`Generic congressional ballot average. Democrats ${(cur.dem * 100).toFixed(1)} percent, Republicans ${(cur.rep * 100).toFixed(1)} percent.`}>
          {gridVals.map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} className="gb-grid" />
              <text x={PAD.left - 10} y={y(v) + 4} className="gb-axis gb-axis-y">
                {Math.round(v * 100)}
                {v === gridVals[gridVals.length - 1] ? "%" : ""}
              </text>
            </g>
          ))}
          {ticks.map(([month, i], tickIndex) => {
            const { name, year } = fmtMonth(month);
            const anchor = tickAnchorAtIndex(tickIndex, ticks.length);
            const tx = clampTickX(x(i), tickBounds, anchor);
            return (
              <g key={month}>
                <line x1={x(i)} x2={x(i)} y1={PAD.top} y2={H - PAD.bottom} className="gb-grid gb-grid-v" />
                <text x={tx} y={H - PAD.bottom + 18} className="gb-axis" textAnchor={anchor}>{name}</text>
                {month.endsWith("-01") ? (
                  <text x={tx} y={H - PAD.bottom + 32} className="gb-axis gb-axis-year" textAnchor={anchor}>
                    {year}
                  </text>
                ) : null}
              </g>
            );
          })}
          <path d={band("repLo", "repHi")} className="gb-band gb-band-rep" />
          <path d={band("demLo", "demHi")} className="gb-band gb-band-dem" />
          <path d={line("rep")} className="gb-line gb-line-rep" />
          <path d={line("dem")} className="gb-line gb-line-dem" />
          <circle cx={x(rows.length - 1)} cy={y(last.dem)} r={4} className="gb-dot gb-dot-dem" />
          <circle cx={x(rows.length - 1)} cy={y(last.rep)} r={4} className="gb-dot gb-dot-rep" />
          <text x={W - PAD.right + 14} y={demLabelY - 2} className="gb-label gb-label-dem">Democrats</text>
          <text x={W - PAD.right + 14} y={demValueY} className="gb-value gb-label-dem">
            {(cur.dem * 100).toFixed(1)}%
          </text>
          <text x={W - PAD.right + 14} y={repLabelY - 2} className="gb-label gb-label-rep">Republicans</text>
          <text x={W - PAD.right + 14} y={repValueY} className="gb-value gb-label-rep">
            {(cur.rep * 100).toFixed(1)}%
          </text>
        </svg>
      ) : (
        <div className="gb-margin">
          <p className="gb-margin-value">
            {leader} {cur.margin_pp >= 0 ? "+" : ""}
            {cur.margin_pp.toFixed(1)}
          </p>
          <p className="cap">
            Two-party Democratic share {(cur.dem_two_party * 100).toFixed(1)}%, band{" "}
            {(cur.lo * 100).toFixed(1)}–{(cur.hi * 100).toFixed(1)}%.
          </p>
        </div>
      )}

      <p className="gb-note">
        {Math.round(doc.band_coverage * 100)}% of polls are projected to fall within the shaded
        regions, combining the spread between polls with the sampling error of one poll.{" "}
        {doc.n_polls} primary polls, {Math.round(doc.half_life_days)}-day recency
        half-life, house effects shrunk toward zero.
        {gate?.single_poll_influence_pp != null
          ? ` No single poll moves the average by more than ${gate.single_poll_influence_pp.toFixed(1)} points.`
          : ""}{" "}
        Updated {doc.generated_at ?? doc.as_of}, covering polls through {doc.as_of}.
      </p>
      {gate && !gate.ok ? (
        <p className="gb-note">
          Seat forecasts are holding a neutral national environment for now —{" "}
          {gate.reasons.join("; ")}. The average above is unaffected.
        </p>
      ) : null}
    </div>
  );
}
