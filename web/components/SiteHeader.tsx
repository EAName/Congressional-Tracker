import Link from "next/link";

export default function SiteHeader({ active }: { active: "scorecard" | "methodology" }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand-block">
          <p className="product">Congressional Vote Tracker</p>
          <h1 className="brand">Democrats for Virginia</h1>
        </div>
        <nav className="site-nav" aria-label="Primary">
          <Link href="/" aria-current={active === "scorecard" ? "page" : undefined}>
            Scorecard
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
