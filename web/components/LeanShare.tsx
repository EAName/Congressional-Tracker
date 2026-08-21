"use client";

type LeanShareProps = {
  demShare: number;
  /** House district vs statewide Senate. */
  geographyLabel: "District" | "Statewide";
};

function formatMargin(demShare: number): string {
  const marginPp = (demShare - 0.5) * 200; // two-party share → Dem margin in points
  if (Math.abs(marginPp) < 0.05) return "Even";
  const abs = Math.abs(marginPp).toFixed(1);
  return marginPp > 0 ? `D+${abs}` : `R+${abs}`;
}

/** Two-party presidential lean: headline share plus a 50%-marked bar. */
export default function LeanShare({ demShare, geographyLabel }: LeanShareProps) {
  const demPct = demShare * 100;
  const repPct = (1 - demShare) * 100;
  const demWins = demShare >= 0.5;

  return (
    <div className="lean-share">
      <div className="lean-share-head">
        <p className={`lean-share-big ${demWins ? "dem" : "rep"}`}>
          {demPct.toFixed(1)}%
          <span className="lean-share-big-sub"> Democratic</span>
        </p>
        <p className="lean-share-margin">{formatMargin(demShare)}</p>
      </div>

      <div
        className="lean-share-bar"
        role="img"
        aria-label={`${geographyLabel} 2024 presidential two-party lean: Democrats ${demPct.toFixed(1)} percent, Republicans ${repPct.toFixed(1)} percent`}
      >
        <div className="lean-share-fill dem" style={{ width: `${demPct}%` }} />
        <div className="lean-share-fill rep" style={{ width: `${repPct}%` }} />
        <div className="lean-share-mid" aria-hidden />
      </div>

      <div className="lean-share-legend">
        <span className="dem">Dem {demPct.toFixed(1)}%</span>
        <span className="lean-share-legend-mid">50%</span>
        <span className="rep">Rep {repPct.toFixed(1)}%</span>
      </div>
    </div>
  );
}
