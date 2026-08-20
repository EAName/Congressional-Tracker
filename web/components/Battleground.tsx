"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import EnvSlider from "@/components/EnvSlider";
import { interpolateGrid } from "@/lib/env";
import type { Meta, RaceEntry, SeatsDoc } from "@/lib/types";

function pct(p: number) {
  return `${Math.round(p * 100)}%`;
}

export default function Battleground({
  races,
  seats,
  meta,
}: {
  races: RaceEntry[];
  seats: SeatsDoc;
  meta: Meta;
}) {
  const grid = seats.env_grid;
  const [margin, setMargin] = useState(grid?.default_margin_pp ?? 0);
  const live = useMemo(() => {
    if (!grid) return [];
    return seats.races.map((seat) => {
      const series = grid.probs[seat.race_id] ?? seat.env_probs ?? [];
      const p = interpolateGrid(grid.margin_pp, series, margin);
      return { seat, p };
    });
  }, [seats.races, grid, margin]);
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
              <p className="seat-kicker">VA-{entry.district}</p>
              <p className="seat-matchup">
                {entry.incumbent.name} vs {entry.challenger.name}
              </p>
              <p className={`seat-big ${p >= 0.5 ? "dem" : "rep"}`}>{pct(p)} Dem</p>
              <p className="seat-cap">
                {meta.days_until_election != null
                  ? `${meta.days_until_election} days to ${meta.election_date}`
                  : entry.election_date}
              </p>
              <p className="seat-plain">{seat.takeaway}</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
