import Link from "next/link";
import { brand } from "@/lib/brand";

export default function SiteHeader({
  active,
  daysUntilElection,
  electionDate,
}: {
  active: "overview" | "analysis" | "methodology" | "about";
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
          {brand.product_name !== brand.site_name ? (
            <p className="product">{brand.product_name}</p>
          ) : null}
          <h1 className="brand">{brand.site_name}</h1>
          {countdown ? <p className="election-countdown">{countdown}</p> : null}
        </div>
        <nav className="site-nav" aria-label="Primary">
          <Link href="/" aria-current={active === "overview" ? "page" : undefined}>
            Battlegrounds
          </Link>
          <Link href="/analysis" aria-current={active === "analysis" ? "page" : undefined}>
            Analysis
          </Link>
          <Link href="/methodology" aria-current={active === "methodology" ? "page" : undefined}>
            Methodology
          </Link>
          <Link href="/about" aria-current={active === "about" ? "page" : undefined}>
            About
          </Link>
        </nav>
      </div>
    </header>
  );
}
