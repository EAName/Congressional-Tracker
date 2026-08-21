"use client";

import { fmtScore } from "@/lib/viz";
import { themeLabel } from "@/lib/types";
import type { HeadToHeadRace, RaceEntry } from "@/lib/types";

const ERA_CAPTION_DEFAULT =
  "Scored on historical Congress votes; themes matched by adjudication, not identical bills. Cross-era comparison is indicative, not exact.";

function ScoreBar({
  label,
  score,
  credLo,
  credHi,
  n,
  historical,
  missingLabel,
}: {
  label: string;
  score: number | null | undefined;
  credLo: number | null | undefined;
  credHi: number | null | undefined;
  n: number | null | undefined;
  historical?: boolean;
  missingLabel?: string;
}) {
  if (score == null) {
    return (
      <div className="h2h-row">
        <span className="h2h-name">{label}</span>
        <span className="h2h-missing">{missingLabel ?? "No score"}</span>
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

function ThemeBars({
  entry,
  race,
  challengerMissing,
}: {
  entry: RaceEntry;
  race: HeadToHeadRace;
  challengerMissing?: string;
}) {
  const incLast = entry.incumbent.name.split(" ").slice(-1)[0];
  const chLast = entry.challenger.name.split(" ").slice(-1)[0];
  return (
    <>
      {race.themes.map((row) => (
        <div key={row.theme} className="h2h-theme">
          <h4>{themeLabel(row.theme)}</h4>
          <ScoreBar
            label={incLast}
            score={row.incumbent?.eb_score}
            credLo={row.incumbent?.cred_lo}
            credHi={row.incumbent?.cred_hi}
            n={row.incumbent?.n_contested}
          />
          <ScoreBar
            label={chLast}
            score={row.challenger?.eb_score}
            credLo={row.challenger?.cred_lo}
            credHi={row.challenger?.cred_hi}
            n={row.challenger?.n_contested}
            historical
            missingLabel={challengerMissing}
          />
        </div>
      ))}
    </>
  );
}

export default function HeadToHead({
  entry,
  race,
}: {
  entry: RaceEntry;
  race: HeadToHeadRace | undefined;
}) {
  if (!race) {
    return (
      <div className="h2h-block">
        <p className="cap">Head-to-head payload missing for this race. Re-run vact export-web.</p>
      </div>
    );
  }

  if (race.status === "no_federal_record" && race.themes.length === 0) {
    return (
      <div className="h2h-block">
        <p className="cap">
          {entry.chamber === "Senate" ? (
            <>
              No scored Senate voting record on this axis yet for {entry.incumbent.name} (Senate
              PASSAGE/AMENDMENT tags + HUMAN valence still pending). {entry.challenger.name} has
              no prior House record to compare.
            </>
          ) : (
            <>
              No scored voting record for {entry.incumbent.name} or {entry.challenger.name} on this
              axis yet.
            </>
          )}
        </p>
      </div>
    );
  }

  if (race.status === "incumbent_only" || (race.incumbent_only && race.themes.length > 0 && race.status === "no_federal_record")) {
    return (
      <div className="h2h-block">
        <p className="cap">
          {entry.challenger.name} has no prior House voting record. Showing {entry.incumbent.name}
          &rsquo;s live scores only.
        </p>
        <ThemeBars
          entry={entry}
          race={race}
          challengerMissing="No House record"
        />
      </div>
    );
  }

  if (race.status === "pending_adjudication") {
    return (
      <div className="h2h-block">
        <p className="cap">
          {entry.challenger.name}&rsquo;s historical roll calls are identified; challenger scores
          publish after adjudication in <code>historical_rollcall_review.csv</code>. Incumbent
          scores below are live.
        </p>
        {race.era_caption ? (
          <p className="h2h-era-caption" aria-live="polite">
            {race.era_caption}
          </p>
        ) : null}
        {race.themes.length > 0 ? (
          <ThemeBars
            entry={entry}
            race={race}
            challengerMissing="Awaiting adjudication"
          />
        ) : null}
      </div>
    );
  }

  if (race.themes.length === 0) {
    return (
      <div className="h2h-block">
        <p className="cap">No theme scores available for this matchup yet.</p>
      </div>
    );
  }

  const caption = race.era_caption ?? ERA_CAPTION_DEFAULT;

  return (
    <div className="h2h-block">
      <p className="h2h-era-caption" aria-live="polite">
        {caption}
      </p>
      <ThemeBars entry={entry} race={race} />
    </div>
  );
}
