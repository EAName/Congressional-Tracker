import Link from "next/link";
import { notFound } from "next/navigation";
import SiteHeader from "@/components/SiteHeader";
import SeatForecast from "@/components/SeatForecast";
import type { Meta, RacesDoc, SeatsDoc } from "@/lib/types";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;

export function generateStaticParams() {
  return races.races.map((r) => ({ raceId: r.race_id }));
}

export default async function RacePage({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  if (!entry || !seat) notFound();

  return (
    <div className="shell">
      <SiteHeader
        active="races"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <div className="workspace">
        <p className="race-nav">
          <Link href="/">Scorecard</Link>
          {races.races.map((r) => (
            <Link key={r.race_id} href={`/races/${r.race_id}`} aria-current={r.race_id === entry.race_id ? "page" : undefined}>
              VA-{r.district}
            </Link>
          ))}
        </p>
        <section className="module span-12">
          <header className="module-head">
            <div>
              <h2 className="module-title">VA-{entry.district} · 2026</h2>
              <p className="module-kicker">Pre-registered seat model {seat.model_version}</p>
            </div>
          </header>
          <div className="module-body">
            <SeatForecast race={seat} entry={entry} log={seats.log} />
          </div>
        </section>
      </div>
    </div>
  );
}
