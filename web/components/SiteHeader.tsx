import Link from "next/link";

export default function SiteHeader({
  active,
  daysUntilElection,
  electionDate,
}: {
  active: "scorecard" | "methodology" | "races";
  daysUntilElection?: number;
  electionDate?: string;
}) {
  const countdown =
    daysUntilElection == null
      ? null
      : daysUntilElection > 0
        ? `${daysUntilElection} days to ${electionDate ?? "election"}`
        : daysUntilElection === 0
          ? "Election day"
          : `${Math.abs(daysUntilElection)} days since ${electionDate ?? "election"}`;

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand-block">
          <p className="product">Congressional Vote Tracker</p>
          <h1 className="brand">Democrats for Virginia</h1>
          {countdown ? <p className="election-countdown">{countdown}</p> : null}
        </div>
        <nav className="site-nav" aria-label="Primary">
          <Link href="/" aria-current={active === "scorecard" ? "page" : undefined}>
            Scorecard
          </Link>
          <Link href="/races" aria-current={active === "races" ? "page" : undefined}>
            Races
          </Link>
          <Link
            href="/methodology"
            aria-current={active === "methodology" ? "page" : undefined}
          >
            Methodology
          </Link>
        </nav>
      </div>
    </header>
  );
}
