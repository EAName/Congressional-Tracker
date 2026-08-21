import Battleground from "@/components/Battleground";
import GenericBallot from "@/components/GenericBallot";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import type { GenericBallotDoc, Meta, RacesDoc, SeatsDoc, SenateDoc } from "@/lib/types";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";
import senateJson from "@/data/senate.json";
import genericBallotJson from "@/data/generic_ballot.json";

export default function Page() {
  const meta = metaJson as Meta;
  const races = racesJson as RacesDoc;
  const seats = seatsJson as SeatsDoc;
  const senate = senateJson as unknown as SenateDoc;
  const genericBallot = genericBallotJson as unknown as GenericBallotDoc;

  return (
    <div className="shell">
      <SiteHeader
        active="overview"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <div className="workspace">
        <section className="module span-12">
          <header className="module-head">
            <div>
              <h2 className="module-title">
                Are Democrats or Republicans winning the race for Congress?
              </h2>
              <p className="module-kicker">
                Our average of 2026 generic congressional ballot polls, weighted by each
                poll&rsquo;s sample size and recency and corrected for house effects
              </p>
            </div>
          </header>
          <div className="module-body">
            <GenericBallot doc={genericBallot} />
          </div>
        </section>

        <section className="module span-12">
          <header className="module-head">
            <div>
              <h2 className="module-title">2026 battlegrounds</h2>
              <p className="module-kicker">
                Tracked House seats plus VA-Sen · election {meta.election_date}
              </p>
            </div>
          </header>
          <div className="module-body">
            <Battleground races={races.races} seats={seats} senate={senate} meta={meta} />
          </div>
        </section>
      </div>
      <SiteFooter />
    </div>
  );
}
