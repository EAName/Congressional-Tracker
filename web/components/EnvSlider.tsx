"use client";

import { formatMargin } from "@/lib/env";
import type { EnvGrid } from "@/lib/types";

export default function EnvSlider({
  grid,
  value,
  onChange,
}: {
  grid: EnvGrid;
  value: number;
  onChange: (next: number) => void;
}) {
  const offDefault = Math.abs(value - grid.default_margin_pp) > 0.05;
  return (
    <div className="env-slider">
      <div className="env-slider-head">
        <p className="seat-kicker">National environment (generic ballot Dem margin)</p>
        <p className="env-slider-value">{formatMargin(value)}</p>
      </div>
      <input
        type="range"
        min={grid.min}
        max={grid.max}
        step={grid.step}
        value={value}
        aria-label="Generic ballot Democratic margin in points"
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="env-slider-meta">
        <span>R+4</span>
        <span className={!offDefault ? "is-current" : undefined}>
          current average {formatMargin(grid.default_margin_pp)}
        </span>
        <span>D+12</span>
      </div>
      {offDefault ? (
        <p className="env-scenario">
          Scenario, not forecast.{" "}
          <button type="button" className="env-reset" onClick={() => onChange(grid.default_margin_pp)}>
            Reset to current average
          </button>
        </p>
      ) : (
        <p className="seat-cap">Slider at the latest generic-ballot row (or even if none is logged).</p>
      )}
    </div>
  );
}
