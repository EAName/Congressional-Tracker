import { notFound } from "next/navigation";
import RaceDisclaimer from "@/components/RaceDisclaimer";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import RaceWorkspace from "@/components/RaceWorkspace";
import type { FecDoc, Meta, RacesDoc, SeatsDoc, TimeSeriesDoc } from "@/lib/types";
import fecJson from "@/data/fec.json";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";
import timeseriesJson from "@/data/timeseries.json";

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;
const fec = fecJson as FecDoc;
const timeseries = timeseriesJson as TimeSeriesDoc;

export function generateStaticParams() {
  return races.races.map((r) => ({ raceId: r.race_id }));
}

export async function generateMetadata({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  if (!entry || !seat) return { title: "Race" };
  return {
    title: `VA-${entry.district} · ${Math.round(seat.prob_dem * 100)}% Dem · Democrats for Virginia`,
    description: seat.takeaway ?? seat.plain_language,
  };
}

export default async function RacePage({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  if (!entry || !seat) notFound();
  const fecRows = (fec.snapshot?.candidates ?? []).filter((c) => c.race_id === entry.race_id);

  return (
    <div className="shell">
      <SiteHeader
        active="overview"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <div className="workspace">
        <RaceDisclaimer raceId={entry.race_id} />
        <RaceWorkspace
          entry={entry}
          seat={seat}
          seats={seats}
          fec={fecRows}
          timeseries={timeseries}
          meta={meta}
        />
      </div>
      <SiteFooter />
    </div>
  );
}
