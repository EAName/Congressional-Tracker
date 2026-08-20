"use client";

import { useMemo, useState } from "react";
import EnvSlider from "@/components/EnvSlider";
import FecBars from "@/components/FecBars";
import SeatForecast from "@/components/SeatForecast";
import ScoreOverTime from "@/components/ScoreOverTime";
import Module from "@/components/Module";
import { interpolateGrid } from "@/lib/env";
import { themeLabel } from "@/lib/types";
import type {
  FecCandidate,
  Meta,
  RaceEntry,
  SeatRace,
  SeatsDoc,
  TimeSeriesDoc,
} from "@/lib/types";

export default function RaceWorkspace({
  entry,
  seat,
  seats,
  fec,
  timeseries,
  meta,
}: {
  entry: RaceEntry;
  seat: SeatRace;
  seats: SeatsDoc;
  fec: FecCandidate[];
  timeseries: TimeSeriesDoc;
  meta: Meta;
}) {
  const grid = seats.env_grid;
  const [margin, setMargin] = useState(grid?.default_margin_pp ?? 0);
  const theme = meta.themes[0];
  const incumbentId = entry.incumbent.bioguide_id ?? null;
  const cell = useMemo(
    () =>
      timeseries.series.find((s) => s.bioguide_id === incumbentId && s.theme === theme) ??
      timeseries.series.find((s) => s.bioguide_id === incumbentId) ??
      null,
    [timeseries.series, incumbentId, theme],
  );
  if (!grid) {
    return <p className="cap">Environment grid missing. Run vact export-web.</p>;
  }
  const series = grid.probs[seat.race_id] ?? seat.env_probs ?? [];
  const p = interpolateGrid(grid.margin_pp, series, margin);
  const live: SeatRace = {
    ...seat,
    prob_dem: p,
    prob_rep: 1 - p,
    plain_language:
      Math.abs(margin - grid.default_margin_pp) > 0.05
        ? `${seat.plain_language} under this scenario`
        : seat.plain_language,
  };

  return (
    <div className="module-grid">
      <div className="span-12">
        <EnvSlider grid={grid} value={margin} onChange={setMargin} />
      </div>
      <Module title={`VA-${entry.district} probability`} kicker={live.takeaway} span={12}>
        <SeatForecast race={live} entry={entry} log={seats.log} />
      </Module>
      <Module title="Head to head" kicker="Prompt 11" span={6}>
        <p className="cap">
          Challenger House scores use the same themes, adjudication schema, and EB shrinkage as
          incumbents. That module ships when historical rollcalls are adjudicated.
        </p>
      </Module>
      <Module title="Record vs district" kicker="Prompt 12" span={6}>
        <p className="cap">
          Gap between the voting record and the district presidential baseline lands after lean
          shares in races.json are filled and Prompt 12 runs.
        </p>
      </Module>
      <Module
        title="Incumbent score over time"
        kicker={incumbentId ? themeLabel(cell?.theme ?? theme) : "No bioguide"}
        span={12}
      >
        <ScoreOverTime
          cell={cell}
          selectedId={incumbentId}
          themeLabel={themeLabel(cell?.theme ?? theme)}
        />
      </Module>
      <Module title="Fundraising snapshot" kicker="OpenFEC totals" span={12}>
        <FecBars candidates={fec} />
      </Module>
    </div>
  );
}
