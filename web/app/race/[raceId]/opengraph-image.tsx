import { ImageResponse } from "next/og";
import { brand } from "@/lib/brand";
import { formatElectionCountdown } from "@/lib/election";
import { raceLabel } from "@/lib/types";
import type { Meta, RacesDoc, SeatsDoc } from "@/lib/types";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;

export default async function OgImage({ params }: { params: Promise<{ raceId: string }> }) {
  const { raceId } = await params;
  const entry = races.races.find((r) => r.race_id === raceId);
  const seat = seats.races.find((r) => r.race_id === raceId);
  const label = entry ? raceLabel(entry) : "";
  const p = seat ? Math.round(seat.prob_dem * 100) : "—";
  const countdown = meta.election_date
    ? formatElectionCountdown(meta.election_date)
    : meta.election_date;
  const matchup = entry
    ? `${entry.incumbent.name} vs ${entry.challenger.name}`
    : raceId;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#14120f",
          color: "#f4efe4",
          padding: "64px",
          fontFamily: "Georgia, serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 22, letterSpacing: 4, textTransform: "uppercase", color: "#a89f8e" }}>
            {brand.site_name}
          </div>
          <div style={{ fontSize: 64, fontWeight: 700 }}>{label}</div>
          <div style={{ fontSize: 28, color: "#d9d0c0" }}>{matchup}</div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 18, color: "#a89f8e" }}>Democratic win probability</div>
            <div style={{ fontSize: 72, fontWeight: 700 }}>{p}%</div>
          </div>
          <div style={{ fontSize: 24, color: "#d9d0c0" }}>{countdown}</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
