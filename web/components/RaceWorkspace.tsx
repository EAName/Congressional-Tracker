"use client";

import { useMemo, useState } from "react";
import EnvSlider from "@/components/EnvSlider";
import FecBars from "@/components/FecBars";
import HeadToHead from "@/components/HeadToHead";
import LeanTrend from "@/components/LeanTrend";
import LeanShare from "@/components/LeanShare";
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
  const houseGrid = seats.env_grid;
  const senateGrid = senateDoc?.env_grid;
  const activeGrid = seat ? houseGrid : senate ? senateGrid : houseGrid;
  const [margin, setMargin] = useState(
    () => activeGrid?.default_margin_pp ?? houseGrid?.default_margin_pp ?? 0,
  );
  const theme = meta.themes[0];
  const incumbentId = entry.incumbent.bioguide_id ?? null;
  // Same source as the head-to-head block, so the two cannot contradict each other
  // about what is outstanding on this race.
  const pendingValence = headToHead?.races?.[entry.race_id]?.pending_valence ?? 0;
  const cell = useMemo(
    () =>
      timeseries.series.find((s) => s.bioguide_id === incumbentId && s.theme === theme) ??
      timeseries.series.find((s) => s.bioguide_id === incumbentId) ??
      null,
    [timeseries.series, incumbentId, theme],
  );

  if (!houseGrid && !senateGrid) {
    return <p className="cap">Environment grid missing. Run vact export-web.</p>;
  }

  const label = raceLabel(entry);
  let live: SeatRace | null = null;
  if (seat && houseGrid) {
    const series = houseGrid.probs[seat.race_id] ?? seat.env_probs ?? [];
    const p = interpolateGrid(houseGrid.margin_pp, series, margin);
    live = {
      ...seat,
      prob_dem: p,
      prob_rep: 1 - p,
      plain_language:
        Math.abs(margin - houseGrid.default_margin_pp) > 0.05
          ? `${seat.plain_language} under this scenario`
          : seat.plain_language,
    };
  }

  let liveSenate: SenateRace | null = null;
  if (senate) {
    const grid = senateGrid;
    if (grid) {
      const series = grid.probs[senate.race_id] ?? senate.env_probs ?? [];
      const p = interpolateGrid(grid.margin_pp, series, margin);
      liveSenate = { ...senate, prob_dem: p, prob_rep: 1 - p };
    } else {
      liveSenate = senate;
    }
  }

  const leanShare = entry.district_lean?.pres_2024_two_party_dem_share ?? null;
  const leanHistory = entry.district_lean?.history ?? [];
  const isSenate = entry.chamber === "Senate";

  return (
    <div className="module-grid">
      {(live || liveSenate) && activeGrid ? (
        <div className="span-12">
          <EnvSlider grid={activeGrid} value={margin} onChange={setMargin} />
        </div>
      ) : null}
      {live ? (
        <Module title={`${label} probability`} kicker={live.takeaway} span={12}>
          <SeatForecast race={live} entry={entry} log={seats.log} />
        </Module>
      ) : liveSenate ? (
        <Module
          title={`${label} probability`}
          kicker={`${liveSenate.model_version} · statewide model`}
          span={12}
        >
          <div className="sen-forecast">
            <p className="sen-headline">
              <strong>{Math.round(liveSenate.prob_dem * 100)}%</strong> Democratic ·{" "}
              {Math.round(liveSenate.prob_rep * 100)}% Republican
            </p>
            <p className="cap">
              Central estimate {(liveSenate.mu_dem_two_party * 100).toFixed(1)}% of the
              two-party vote, 80% interval{" "}
              {(liveSenate.share_lo * 100).toFixed(1)}–{(liveSenate.share_hi * 100).toFixed(1)}%.{" "}
              {liveSenate.blend === "fundamentals_only"
                ? "Fundamentals only — no state polls in the log."
                : `Blended with ${liveSenate.n_polls} state poll(s).`}
            </p>
            <dl className="sen-decomp">
              {Object.entries(liveSenate.decomposition).map(([k, v]) => (
                <div key={k} className="sen-decomp-row">
                  <dt>{k.replace(/_/g, " ")}</dt>
                  <dd>
                    {v >= 0 ? "+" : ""}
                    {(v * 100).toFixed(1)}
                  </dd>
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
        title={isSenate ? "Statewide lean" : "District lean"}
        kicker={
          leanHistory.length > 1
            ? `Presidential two-party Dem share, ${leanHistory[0].year}\u2013${leanHistory[leanHistory.length - 1].year}`
            : "2024 presidential two-party Dem share"
        }
        span={6}
      >
        {leanHistory.length ? (
          <LeanTrend
            history={leanHistory}
            geographyLabel={isSenate ? "Statewide" : "District"}
          />
        ) : leanShare != null ? (
          <LeanShare
            demShare={leanShare}
            geographyLabel={isSenate ? "Statewide" : "District"}
          />
        ) : (
          <p className="cap">Presidential lean not yet filled for this race.</p>
        )}
      </Module>
      <Module
        title="Incumbent score over time"
        kicker={
          incumbentId
            ? themeLabel(cell?.theme ?? theme)
            : "No bioguide"
        }
        span={12}
      >
        {isSenate && !cell ? (
          <p className="cap">
            {pendingValence > 0 ? (
              <>
                {entry.incumbent.name}&rsquo;s Senate roll calls are ingested and{" "}
                {pendingValence} {pendingValence === 1 ? "vote is" : "votes are"} tagged to a
                theme. The series publishes once those carry a HUMAN-adjudicated valence;
                nothing else is outstanding.
              </>
            ) : (
              <>
                {entry.incumbent.name}&rsquo;s Senate roll calls are ingested, but no
                scoreable vote carries a theme tag yet, so there is nothing to adjudicate.
              </>
            )}
          </p>
        ) : (
          <ScoreOverTime
            cell={cell}
            selectedId={incumbentId}
            themeLabel={themeLabel(cell?.theme ?? theme)}
          />
        )}
      </Module>
      <Module title="Fundraising snapshot" kicker="OpenFEC totals" span={12}>
        <FecBars candidates={fec} />
      </Module>
    </div>
  );
}
