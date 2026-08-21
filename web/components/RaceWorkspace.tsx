"use client";

import { useMemo, useState } from "react";
import EnvSlider from "@/components/EnvSlider";
import FecBars from "@/components/FecBars";
import HeadToHead from "@/components/HeadToHead";
import SeatForecast from "@/components/SeatForecast";
import ScoreOverTime from "@/components/ScoreOverTime";
import Module from "@/components/Module";
import { interpolateGrid } from "@/lib/env";
import { raceLabel, themeLabel } from "@/lib/types";
import type {
  FecCandidate,
  HeadToHeadDoc,
  Meta,
  RaceEntry,
  SeatRace,
  SeatsDoc,
  SenateDoc,
  SenateRace,
  TimeSeriesDoc,
} from "@/lib/types";

export default function RaceWorkspace({
  entry,
  seat,
  senate,
  senateDoc,
  seats,
  fec,
  timeseries,
  meta,
  headToHead,
}: {
  entry: RaceEntry;
  /** Absent when the House-fit seat model does not score this race (Senate). */
  seat?: SeatRace;
  /** Present for Senate races, scored by senate-v0.1 instead. */
  senate?: SenateRace;
  senateDoc?: SenateDoc;
  seats: SeatsDoc;
  fec: FecCandidate[];
  timeseries: TimeSeriesDoc;
  meta: Meta;
  headToHead?: HeadToHeadDoc;
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
  const label = raceLabel(entry);
  let live: SeatRace | null = null;
  if (seat) {
    const series = grid.probs[seat.race_id] ?? seat.env_probs ?? [];
    const p = interpolateGrid(grid.margin_pp, series, margin);
    live = {
      ...seat,
      prob_dem: p,
      prob_rep: 1 - p,
      plain_language:
        Math.abs(margin - grid.default_margin_pp) > 0.05
          ? `${seat.plain_language} under this scenario`
          : seat.plain_language,
    };
  }

  return (
    <div className="module-grid">
      {live ? (
        <div className="span-12">
          <EnvSlider grid={grid} value={margin} onChange={setMargin} />
        </div>
      ) : null}
      {live ? (
        <Module title={`${label} probability`} kicker={live.takeaway} span={12}>
          <SeatForecast race={live} entry={entry} log={seats.log} />
        </Module>
      ) : senate ? (
        <Module
          title={`${label} probability`}
          kicker={`${senate.model_version} · statewide model`}
          span={12}
        >
          <div className="sen-forecast">
            <p className="sen-headline">
              <strong>{Math.round(senate.prob_dem * 100)}%</strong> Democratic ·{" "}
              {Math.round(senate.prob_rep * 100)}% Republican
            </p>
            <p className="cap">
              Central estimate {(senate.mu_dem_two_party * 100).toFixed(1)}% of the
              two-party vote, 80% interval{" "}
              {(senate.share_lo * 100).toFixed(1)}–{(senate.share_hi * 100).toFixed(1)}%.{" "}
              {senate.blend === "fundamentals_only"
                ? "Fundamentals only — no state polls in the log."
                : `Blended with ${senate.n_polls} state poll(s).`}
            </p>
            <dl className="sen-decomp">
              {Object.entries(senate.decomposition).map(([k, v]) => (
                <div key={k} className="sen-decomp-row">
                  <dt>{k.replace(/_/g, " ")}</dt>
                  <dd>{v >= 0 ? "+" : ""}{(v * 100).toFixed(1)}</dd>
                </div>
              ))}
            </dl>
            {senateDoc ? (
              <p className="cap">
                Fit on {senateDoc.fit.n_train} races across{" "}
                {senateDoc.fit.cycles.length} cycles. Leave-one-cycle-out Brier{" "}
                {senateDoc.fit.cv.brier_model} against {senateDoc.fit.cv.brier_lean_swing}{" "}
                for lean-plus-uniform-swing and {senateDoc.fit.cv.brier_always_incumbent}{" "}
                for always-incumbent. The House seat model does not score this race —
                it has no statewide baseline to feed it.
              </p>
            ) : null}
          </div>
        </Module>
      ) : (
        <Module title={`${label} probability`} kicker="Not modeled" span={12}>
          <p className="cap">No win probability published for {label}.</p>
        </Module>
      )}
      <Module title="Head to head" kicker="Same-method scores" span={6}>
        <HeadToHead entry={entry} race={headToHead?.races[entry.race_id]} />
      </Module>
      <Module
        title={entry.chamber === "Senate" ? "Record vs state" : "Record vs district"}
        kicker="Prompt 12"
        span={6}
      >
        <p className="cap">
          Gap between the voting record and the{" "}
          {entry.chamber === "Senate" ? "statewide" : "district"} presidential baseline lands
          after lean shares in races.json are filled and Prompt 12 runs.
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
