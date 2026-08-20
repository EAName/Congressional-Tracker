import Battleground from "@/components/Battleground";
import SiteHeader from "@/components/SiteHeader";
import type { Meta, RacesDoc, SeatsDoc } from "@/lib/types";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";

export default function Page() {
  const meta = metaJson as Meta;
  const races = racesJson as RacesDoc;
  const seats = seatsJson as SeatsDoc;

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
              <h2 className="module-title">2026 battlegrounds</h2>
              <p className="module-kicker">
                Three tracked seats on the 2021 map · election {meta.election_date}
              </p>
            </div>
          </header>
          <div className="module-body">
            <Battleground races={races.races} seats={seats} meta={meta} />
          </div>
        </section>
      </div>
    </div>
  );
}
