import { notFound } from "next/navigation";
import RaceDisclaimer from "@/components/RaceDisclaimer";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import RaceWorkspace from "@/components/RaceWorkspace";
import { pageTitle } from "@/lib/brand";
import { raceLabel } from "@/lib/types";
import type {
  FecDoc,
  HeadToHeadDoc,
  Meta,
  RacesDoc,
  SeatsDoc,
  SenateDoc,
  TimeSeriesDoc,
} from "@/lib/types";
import fecJson from "@/data/fec.json";
import headToHeadJson from "@/data/head_to_head.json";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";
import senateJson from "@/data/senate.json";
import timeseriesJson from "@/data/timeseries.json";

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;
const senate = senateJson as unknown as SenateDoc;
const fec = fecJson as FecDoc;
const timeseries = timeseriesJson as TimeSeriesDoc;
const headToHead = headToHeadJson as HeadToHeadDoc;

export function generateStaticParams() {
  return races.races.map((r) => ({ raceId: r.race_id }));
}

export async function generateMetadata({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  const sen = senate.races.find((r) => r.race_id === raceId);
  if (!entry) return { title: "Race" };
  const label = raceLabel(entry);
  if (sen) {
    return {
      title: pageTitle(`${label} · ${Math.round(sen.prob_dem * 100)}% Dem`),
      description: `${entry.incumbent.name} vs ${entry.challenger.name}, ${entry.election_date}.`,
    };
  }
  if (!seat) {
    return {
      title: pageTitle(label),
      description: `${entry.incumbent.name} vs ${entry.challenger.name}, ${entry.election_date}.`,
    };
  }
  return {
    title: pageTitle(`${label} · ${Math.round(seat.prob_dem * 100)}% Dem`),
    description: seat.takeaway ?? seat.plain_language,
  };
}

export default async function RacePage({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  const senateRace = senate.races.find((r) => r.race_id === raceId);
  if (!entry) notFound();
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
          senate={senateRace}
          senateDoc={senate}
          seats={seats}
          fec={fecRows}
          timeseries={timeseries}
          meta={meta}
          headToHead={headToHead}
        />
      </div>
      <SiteFooter />
    </div>
  );
}
