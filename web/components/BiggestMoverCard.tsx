"use client";

import type { BiggestMover } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { fmtScore } from "@/lib/viz";

export default function BiggestMoverCard({
  mover,
  onSelect,
}: {
  mover: BiggestMover | null;
  onSelect: (id: string, theme: string) => void;
}) {
  if (!mover) {
    return <p className="cap">No member-theme cell has both a pre-window observation and a sufficient end point.</p>;
  }
  const up = mover.delta >= 0;
  const who = shortName(mover.full_name);
  const district = mover.district_number != null ? `VA-${mover.district_number}` : mover.chamber;

  return (
    <button
      type="button"
      className="mover"
      onClick={() => onSelect(mover.bioguide_id, mover.theme)}
    >
      <p className="mover-kicker">Largest |Δ| over {mover.window_days}d</p>
      <p className={`mover-who ${mover.party === "Republican" ? "rep" : "dem"}`}>{who}</p>
      <p className="mover-meta">
        {district} · {themeLabel(mover.theme)}
      </p>
      <p className={`mover-delta ${up ? "up" : "down"}`}>
        {fmtScore(mover.delta)}
        <small>
          {fmtScore(mover.start_score)} → {fmtScore(mover.end_score)}
        </small>
      </p>
      <p className="mover-dates">
        {mover.start_date} (n={mover.start_n}) → {mover.end_date} (n={mover.end_n})
      </p>
    </button>
  );
}
