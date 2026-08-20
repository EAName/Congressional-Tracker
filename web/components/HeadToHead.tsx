"use client";

import { fmtScore } from "@/lib/viz";
import { themeLabel } from "@/lib/types";
import type { HeadToHeadDoc, HeadToHeadRace, RaceEntry } from "@/lib/types";

const ERA_CAPTION_DEFAULT =
  "Scored on historical Congress votes; themes matched by adjudication, not identical bills. Cross-era comparison is indicative, not exact.";

function ScoreBar({
  label,
  score,
  credLo,
  credHi,
  n,
  historical,
}: {
  label: string;
  score: number | null | undefined;
  credLo: number | null | undefined;
  credHi: number | null | undefined;
  n: number | null | undefined;
  historical?: boolean;
}) {
  if (score == null) {
    return (
      <div className="h2h-row">
        <span className="h2h-name">{label}</span>
        <span className="h2h-missing">No score</span>
      </div>
    );
  }
  const pct = ((score + 1) / 2) * 100;
  return (
    <div className={`h2h-row${historical ? " h2h-historical" : ""}`}>
      <span className="h2h-name">{label}</span>
      <div className="h2h-bar-wrap">
        <div className="h2h-bar" style={{ width: `${pct}%` }} aria-hidden />
        <span className="h2h-score">{fmtScore(score)}</span>
      </div>
      <span className="h2h-meta">
        n={n ?? "—"}
        {credLo != null && credHi != null ? ` · CI ${fmtScore(credLo)}–${fmtScore(credHi)}` : ""}
      </span>
    </div>
  );
}

export default function HeadToHead({
  entry,
  race,
}: {
  entry: RaceEntry;
  race: HeadToHeadRace | undefined;
}) {
  if (!race || race.status === "no_federal_record") {
    return (
      <div className="h2h-block">
        <p className="cap">
          {entry.challenger.name} has no prior House voting record. Record-vs-district for{" "}
          {entry.incumbent.name} only until Prompt 12.
        </p>
      </div>
    );
  }

  if (race.status === "pending_adjudication" || race.themes.length === 0) {
    return (
      <div className="h2h-block">
        <p className="cap">
          Historical roll calls identified; awaiting human adjudication in{" "}
          <code>historical_rollcall_review.csv</code> and{" "}
          <code>votes_historical_candidates.csv</code>. Run <code>vact historical propose</code>{" "}
          after backfill.
        </p>
        {race.era_caption ? (
          <p className="h2h-era-caption" aria-live="polite">
            {race.era_caption}
          </p>
        ) : null}
      </div>
    );
  }

  const caption = race.era_caption ?? ERA_CAPTION_DEFAULT;

  return (
    <div className="h2h-block">
      <p className="h2h-era-caption" aria-live="polite">
        {caption}
      </p>
      {race.themes.map((row) => (
        <div key={row.theme} className="h2h-theme">
          <h4>{themeLabel(row.theme)}</h4>
          <ScoreBar
            label={entry.incumbent.name.split(" ").slice(-1)[0]}
            score={row.incumbent?.eb_score}
            credLo={row.incumbent?.cred_lo}
            credHi={row.incumbent?.cred_hi}
            n={row.incumbent?.n_contested}
          />
          <ScoreBar
            label={entry.challenger.name.split(" ").slice(-1)[0]}
            score={row.challenger?.eb_score}
            credLo={row.challenger?.cred_lo}
            credHi={row.challenger?.cred_hi}
            n={row.challenger?.n_contested}
            historical
          />
        </div>
      ))}
    </div>
  );
}
