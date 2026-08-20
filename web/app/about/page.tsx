import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import type { AboutDoc, Meta } from "@/lib/types";
import { pageTitle } from "@/lib/brand";
import aboutJson from "@/data/about.json";
import metaJson from "@/data/meta.json";
import type { Metadata } from "next";
import Link from "next/link";

const about = aboutJson as AboutDoc;

export const metadata: Metadata = {
  title: pageTitle("About"),
  description: "Publisher identity, affiliations, and independence statement.",
};

export default function AboutPage() {
  const meta = metaJson as Meta;

  return (
    <div className="shell method-shell">
      <SiteHeader
        active="about"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <article className="method">
        <header className="method-head">
          <p className="method-kicker">About</p>
          <h1>{about.title}</h1>
          {about.intro ? <p className="method-lede" dangerouslySetInnerHTML={{ __html: about.intro }} /> : null}
        </header>
        {about.sections.map((section) => (
          <section key={section.heading}>
            <h2>{section.heading}</h2>
            {section.paragraphs.map((p) => (
              <p key={p.slice(0, 40)} dangerouslySetInnerHTML={{ __html: p }} />
            ))}
          </section>
        ))}
        <section>
          <h2>Quick links</h2>
          <ul>
            <li>
              <Link href={about.methodology_href}>Methodology</Link>
            </li>
            <li>
              <Link href={about.symmetry_href}>Symmetry audit</Link>
            </li>
            <li>
              <a href={about.repo_url}>GitHub repository</a>
            </li>
            <li>
              <Link href="/corrections">Corrections policy</Link>
            </li>
          </ul>
        </section>
      </article>
      <SiteFooter />
    </div>
  );
}
