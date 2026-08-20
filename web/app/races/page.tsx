import Link from "next/link";
import SiteHeader from "@/components/SiteHeader";
import type { Meta, RacesDoc, SeatsDoc } from "@/lib/types";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;

export default function RacesIndexPage() {
  return (
    <div className="shell">
      <SiteHeader
        active="races"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <div className="workspace">
        <section className="module span-12">
          <header className="module-head">
            <div>
              <h2 className="module-title">Tracked races</h2>
              <p className="module-kicker">2026 House · map version {races.map_version} · {seats.model_version}</p>
            </div>
          </header>
          <div className="module-body race-index">
            {races.races.map((entry) => {
              const seat = seats.races.find((r) => r.race_id === entry.race_id);
              return (
                <Link key={entry.race_id} href={`/races/${entry.race_id}`} className="race-index-card">
                  <p className="seat-kicker">VA-{entry.district}</p>
                  <p className="seat-matchup">
                    {entry.incumbent.name} vs {entry.challenger.name}
                  </p>
                  <p className="seat-big dem">{seat ? `${Math.round(seat.prob_dem * 100)}%` : "—"}</p>
                  <p className="seat-cap">{seat?.plain_language ?? "No model output"}</p>
                </Link>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
