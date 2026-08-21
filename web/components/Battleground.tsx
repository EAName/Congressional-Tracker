"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import EnvSlider from "@/components/EnvSlider";
import { interpolateGrid } from "@/lib/env";
import { formatElectionCountdown } from "@/lib/election";
import { raceLabel } from "@/lib/types";
import type { Meta, RaceEntry, SeatsDoc, SenateDoc } from "@/lib/types";

function pct(p: number) {
  return `${Math.round(p * 100)}%`;
}

export default function Battleground({
  races,
  seats,
  senate,
  meta,
}: {
  races: RaceEntry[];
  seats: SeatsDoc;
  /** Statewide races, scored by senate-v0.1 rather than the House-fit model. */
  senate?: SenateDoc;
  meta: Meta;
}) {
  const grid = seats.env_grid;
  const [margin, setMargin] = useState(grid?.default_margin_pp ?? 0);
  const [countdown, setCountdown] = useState(() =>
    meta.election_date ? formatElectionCountdown(meta.election_date) : null,
  );
  useEffect(() => {
    if (!meta.election_date) return;
    const tick = () => setCountdown(formatElectionCountdown(meta.election_date!));
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [meta.election_date]);
  const live = useMemo(() => {
    if (!grid) return [];
    return seats.races.map((seat) => {
      const series = grid.probs[seat.race_id] ?? seat.env_probs ?? [];
      const p = interpolateGrid(grid.margin_pp, series, margin);
      return { seat, p };
    });
  }, [seats.races, grid, margin]);
  // The House model reports Senate races as unmodeled; senate-v0.1 scores them.
  // Both grids share the same margin axis, so one slider drives both.
  const senateLive = useMemo(() => {
    if (!senate) return [];
    const sgrid = senate.env_grid;
    return senate.races.map((race) => {
      const series = sgrid?.probs[race.race_id] ?? race.env_probs ?? [];
      const p = sgrid ? interpolateGrid(sgrid.margin_pp, series, margin) : race.prob_dem;
      return { race, p };
    });
  }, [senate, margin]);

  const unmodeled = useMemo(() => {
    const scored = new Set((senate?.races ?? []).map((r) => r.race_id));
    const ids = new Set((seats.unmodeled_races ?? []).filter((id) => !scored.has(id)));
    return races.filter((r) => ids.has(r.race_id));
  }, [races, seats.unmodeled_races, senate]);

  if (!grid) {
    return <p className="cap">Environment grid missing. Run vact export-web.</p>;
  }

  return (
    <div className="battle">
      <EnvSlider grid={grid} value={margin} onChange={setMargin} />
      <div className="battle-grid">
        {live.map(({ seat, p }) => {
          const entry = races.find((r) => r.race_id === seat.race_id);
          if (!entry) return null;
          return (
            <Link key={seat.race_id} href={`/race/${seat.race_id}`} className="battle-card">
              <p className="seat-kicker">{raceLabel(entry)}</p>
              <p className="seat-matchup">
                {entry.incumbent.name} vs {entry.challenger.name}
              </p>
              <p className={`seat-big ${p >= 0.5 ? "dem" : "rep"}`}>{pct(p)} Dem</p>
              <p className="seat-cap">{countdown ?? entry.election_date}</p>
              <p className="seat-plain">{seat.takeaway}</p>
            </Link>
          );
        })}
        {senateLive.map(({ race, p }) => {
          const entry = races.find((r) => r.race_id === race.race_id);
          if (!entry) return null;
          return (
            <Link key={race.race_id} href={`/race/${race.race_id}`} className="battle-card">
              <p className="seat-kicker">{raceLabel(entry)}</p>
              <p className="seat-matchup">
                {entry.incumbent.name} vs {entry.challenger.name}
              </p>
              <p className={`seat-big ${p >= 0.5 ? "dem" : "rep"}`}>{pct(p)} Dem</p>
              <p className="seat-cap">{countdown ?? entry.election_date}</p>
              <p className="seat-plain">{race.takeaway}</p>
              <p className="seat-model">{race.model_version} · statewide model</p>
            </Link>
          );
        })}
        {unmodeled.map((entry) => (
          <Link key={entry.race_id} href={`/race/${entry.race_id}`} className="battle-card">
            <p className="seat-kicker">{raceLabel(entry)}</p>
            <p className="seat-matchup">
              {entry.incumbent.name} vs {entry.challenger.name}
            </p>
            <p className="seat-big">Not modeled</p>
            <p className="seat-cap">{countdown ?? entry.election_date}</p>
            <p className="seat-plain">
              Statewide Senate race excluded from the House-fit seat model.
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
