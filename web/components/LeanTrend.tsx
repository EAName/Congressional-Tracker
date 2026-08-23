"use client";

import type { LeanPoint } from "@/lib/types";

/** Presidential two-party Democratic share across cycles for one geography. */
export default function LeanTrend({
  history,
  geographyLabel,
}: {
  history: LeanPoint[];
  geographyLabel: string;
}) {
  if (!history.length) {
    return <p className="cap">Presidential lean not yet filled for this race.</p>;
  }

  const shares = history.map((h) => h.dem_two_party);
  const lo = Math.min(0.42, ...shares) - 0.02;
  const hi = Math.max(0.58, ...shares) + 0.02;
  const W = 320;
  const H = 96;
  // l/r leave room for the end-year labels; the dashed 50% line is labelled
  // inside the left gutter rather than at the right edge, where it collided
  // with the final dot.
  const PAD = { l: 34, r: 30, t: 14, b: 22 };
  const x = (i: number) =>
    PAD.l + (history.length === 1 ? (W - PAD.l - PAD.r) / 2
      : (i / (history.length - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);

  const line = history
    .map((h, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(h.dem_two_party).toFixed(1)}`)
    .join(" ");
  const latest = history[history.length - 1];
  const marginPp = (latest.dem_two_party * 2 - 1) * 100;
  const anyRounded = history.some((h) => h.precision === "rounded_percent");

  return (
    <div className="lean-trend">
      <p className="lean-headline">
        <strong className={latest.dem_two_party >= 0.5 ? "dem" : "rep"}>
          {(latest.dem_two_party * 100).toFixed(1)}%
        </strong>{" "}
        Democratic in {latest.year}
        <span className="lean-margin">
          {marginPp >= 0 ? "D" : "R"}+{Math.abs(marginPp).toFixed(1)}
        </span>
      </p>

      <svg viewBox={`0 0 ${W} ${H}`} className="lean-svg" role="img"
           aria-label={`${geographyLabel} presidential two-party Democratic share, ${history
             .map((h) => `${h.year} ${(h.dem_two_party * 100).toFixed(1)} percent`)
             .join(", ")}`}>
        <line x1={PAD.l} x2={W - PAD.r} y1={y(0.5)} y2={y(0.5)} className="lean-mid" />
        <text
          x={PAD.l - 8}
          y={y(0.5)}
          className="lean-mid-label"
          textAnchor="end"
          dominantBaseline="middle"
        >
          50%
        </text>
        <path d={line} className="lean-line" />
        {history.map((h, i) => (
          <g key={h.year}>
            <circle
              cx={x(i)}
              cy={y(h.dem_two_party)}
              r={4}
              className={`lean-dot ${h.dem_two_party >= 0.5 ? "is-dem" : "is-rep"}`}
            />
            <text
              x={x(i)}
              y={H - 5}
              className="lean-year"
              textAnchor={
                i === 0 ? "start" : i === history.length - 1 ? "end" : "middle"
              }
            >
              {h.year}
            </text>
          </g>
        ))}
      </svg>

      <p className="cap">
        {geographyLabel} two-party Democratic share across {history.length} presidential
        cycles
        {latest.map_version === "statewide"
          ? " (state boundaries are fixed, so every cycle is comparable)"
          : `, all computed on the ${latest.map_version} map`}
        .
        {anyRounded
          ? " Cycles before 2024 are published to whole percentages, so each carries about ±0.7pp of rounding."
          : ""}
      </p>
    </div>
  );
}
