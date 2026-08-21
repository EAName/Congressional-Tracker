import Link from "next/link";
import ElectionCountdown from "@/components/ElectionCountdown";
import { brand } from "@/lib/brand";

export default function SiteHeader({
  active,
  electionDate,
}: {
  active: "overview" | "analysis" | "methodology" | "about";
  /** @deprecated Ignored — countdown is computed live from electionDate. */
  daysUntilElection?: number;
  electionDate?: string;
}) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand-block">
          {brand.product_name !== brand.site_name ? (
            <p className="product">{brand.product_name}</p>
          ) : null}
          <h1 className="brand">{brand.site_name}</h1>
          {electionDate ? <ElectionCountdown electionDate={electionDate} /> : null}
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
