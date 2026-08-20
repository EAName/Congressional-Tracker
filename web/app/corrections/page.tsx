import { pageTitle } from "@/lib/brand";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import type { Meta } from "@/lib/types";
import metaJson from "@/data/meta.json";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: pageTitle("Corrections policy"),
  description: "How to report factual errors in scores, adjudication, or race data.",
};

export default function CorrectionsPage() {
  const meta = metaJson as Meta;

  return (
    <div className="shell method-shell">
      <SiteHeader
        active="methodology"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <article className="method">
        <header className="method-head">
          <p className="method-kicker">Policy</p>
          <h1>Corrections</h1>
          <p className="method-lede">
            Stub for counsel-approved corrections language. The pipeline is versioned;
            substantive fixes should be traceable in git and reflected on the next export.
          </p>
        </header>

        <section>
          <h2>What to report</h2>
          <ul>
            <li>Incorrect roll-call positions or dates tied to a published source URL</li>
            <li>Adjudication errors in <code>data/votes.csv</code> (axis direction / theme)</li>
            <li>FEC snapshot mismatches against OpenFEC for a listed candidate</li>
            <li>Broken reproduction steps on the methodology page</li>
          </ul>
        </section>

        <section>
          <h2>How to report</h2>
          <p>
            Open an issue in the project repository with the roll-call ID, theme, and a link to
            the official Clerk or Senate record. For sensitive adjudication disputes, use the
            operator channel defined in <code>COMPLIANCE_QUESTIONS.md</code> once counsel
            approves a contact path.
          </p>
        </section>

        <section>
          <h2>Response</h2>
          <p>
            Verified errors are corrected in the adjudication layer or upstream ingest, then
            republished via <code>vact export-web</code>. Historical exports are not rewritten;
            the methodology changelog records git commits that touch scoring inputs.
          </p>
          <p>
            <Link href="/methodology">Return to methodology</Link>
          </p>
        </section>
      </article>
      <SiteFooter />
    </div>
  );
}
