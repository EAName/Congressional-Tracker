import type { RaceEntry, SeatRace, SeatsDoc } from "@/lib/types";

const DECOMP_LABELS: Array<[keyof SeatRace["decomposition"], string]> = [
  ["intercept", "Baseline"],
  ["lean_rel_dem", "Lean"],
  ["inc_dem", "Incumbency"],
  ["midterm_dem", "Midterm"],
  ["log_ratio_dem", "Fundraising"],
  ["qual_dem", "Challenger quality"],
  ["nat_env", "Environment"],
  ["polls", "Polls"],
];

function pct(p: number) {
  return `${Math.round(p * 100)}%`;
}

function odds(p: number) {
  const in5 = Math.max(1, Math.min(5, Math.round(p * 5)));
  return `${in5} in 5`;
}

function Sparkline({ points }: { points: Array<{ date: string; prob: number }> }) {
  if (points.length < 2) {
    return <p className="seat-cap">No history yet. Today is the first logged probability.</p>;
  }
  const w = 280;
  const h = 56;
  const xs = points.map((_, i) => (i / (points.length - 1)) * w);
  const ys = points.map((p) => h - p.prob * h);
  const d = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  return (
    <svg className="seat-spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Win probability over time">
      <line x1="0" y1={h / 2} x2={w} y2={h / 2} className="seat-spark-mid" />
      <path d={d} fill="none" className="seat-spark-line" />
    </svg>
  );
}

export default function SeatForecast({
  race,
  entry,
  log,
}: {
  race: SeatRace;
  entry: RaceEntry;
  log: SeatsDoc["log"];
}) {
  const parts = DECOMP_LABELS.map(([key, label]) => ({
    key,
    label,
    value: race.decomposition[key],
  }));
  const mag = parts.reduce((s, p) => s + Math.abs(p.value), 0) || 1;
  const spark = log
    .filter((r) => r.race_id === race.race_id)
    .map((r) => ({ date: r.date, prob: Number(r.prob_dem) }));

  return (
    <div className="seat-forecast">
      <p className="seat-plain">{race.plain_language}.</p>
      <p className="seat-matchup">
        {entry.incumbent.name} ({entry.incumbent.party === "Republican" ? "R" : "D"}) vs{" "}
        {entry.challenger.name} ({entry.challenger.party === "Republican" ? "R" : "D"})
      </p>
      <div className="seat-probs">
        <div>
          <p className="seat-kicker">P(Dem)</p>
          <p className="seat-big dem">{pct(race.prob_dem)}</p>
          <p className="seat-cap">roughly {odds(race.prob_dem)}</p>
        </div>
        <div>
          <p className="seat-kicker">P(Rep)</p>
          <p className="seat-big rep">{pct(race.prob_rep)}</p>
          <p className="seat-cap">roughly {odds(race.prob_rep)}</p>
        </div>
        <div>
          <p className="seat-kicker">Dem two-party share (80%)</p>
          <p className="seat-big">
            {pct(race.share_lo)}–{pct(race.share_hi)}
          </p>
          <p className="seat-cap">center {pct(race.mu_dem_two_party)}</p>
        </div>
      </div>
      <p className="seat-cap">
        {race.blend === "fundamentals_only"
          ? "Fundamentals prior only (no district polls in the log)."
          : `Blended with ${race.n_polls} district poll(s).`}{" "}
        Model {race.model_version}.
        {race.meta?.lean_status === "missing_zeroed"
          ? " District lean is still a placeholder, so this run zeros lean."
          : null}
      </p>
      <div className="seat-stack" role="img" aria-label="Share decomposition">
        {parts.map((p) => (
          <div key={p.key} className="seat-stack-row">
            <span>{p.label}</span>
            <span
              className={`seat-bar ${p.value >= 0 ? "dem" : "rep"}`}
              style={{ width: `${(Math.abs(p.value) / mag) * 100}%` }}
            />
            <span>{(p.value >= 0 ? "+" : "") + (p.value * 100).toFixed(1)} pp</span>
          </div>
        ))}
      </div>
      <Sparkline points={spark} />
    </div>
  );
}
