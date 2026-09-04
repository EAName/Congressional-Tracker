import { ImageResponse } from "next/og";
import { brand } from "@/lib/brand";
import { raceLabel } from "@/lib/types";
import type { GenericBallotDoc, Meta, RacesDoc, SeatsDoc, SenateDoc } from "@/lib/types";
import genericBallotJson from "@/data/generic_ballot.json";
import metaJson from "@/data/meta.json";
import racesJson from "@/data/races.json";
import seatsJson from "@/data/seats.json";
import senateJson from "@/data/senate.json";

// Baked at build time so it regenerates whenever web/data/*.json changes, and
// revalidated daily so the countdown does not freeze at the deploy date. The
// card carries "N days to 2026-11-03", which drifts by a day every day the site
// is not rebuilt; without this it would be wrong more often than right.
export const dynamic = "force-static";
export const revalidate = 86400;
const SIZE = { width: 1200, height: 630 };

const meta = metaJson as Meta;
const races = racesJson as RacesDoc;
const seats = seatsJson as SeatsDoc;
const senate = senateJson as unknown as SenateDoc;
const genericBallot = genericBallotJson as unknown as GenericBallotDoc;

const BG = "#070b12";
const PANEL = "#121a28";
const INK = "#e8eef8";
const INK2 = "#9aa8bc";
const INK3 = "#6b7a90";
const LINE = "#243044";

/** Continuous red -> blue across the probability range. */
function probColor(p: number): string {
  const stops: Array<[number, [number, number, number]]> = [
    [0.0, [176, 42, 55]],
    [0.35, [239, 83, 80]],
    [0.5, [124, 132, 150]],
    [0.65, [59, 130, 246]],
    [1.0, [30, 78, 180]],
  ];
  const t = Math.max(0, Math.min(1, p));
  for (let i = 0; i < stops.length - 1; i += 1) {
    const [lo, a] = stops[i];
    const [hi, b] = stops[i + 1];
    if (t >= lo && t <= hi) {
      const k = hi === lo ? 0 : (t - lo) / (hi - lo);
      const c = a.map((v, j) => Math.round(v + k * (b[j] - v)));
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    }
  }
  return `rgb(${stops[stops.length - 1][1].join(", ")})`;
}

export async function GET() {
  const byId = new Map<string, number>();
  for (const r of seats.races) byId.set(r.race_id, r.prob_dem);
  for (const r of senate.races) byId.set(r.race_id, r.prob_dem);

  const cells = races.races
    .filter((r) => byId.has(r.race_id))
    .map((r) => ({ label: raceLabel(r), p: byId.get(r.race_id) as number }));

  const gb = genericBallot.current;
  const days = meta.days_until_election;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: BG,
          color: INK,
          padding: "52px 56px",
          fontFamily: "sans-serif",
overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 62, fontWeight: 700, letterSpacing: -1 }}>
            {brand.site_name}
          </div>
          <div style={{ fontSize: 32, color: INK2, marginTop: 6 }}>
            2026 Virginia battlegrounds
          </div>
        </div>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            marginTop: 30,
            width: 1080,
          }}
        >
          {cells.map((c) => (
            <div
              key={c.label}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                width: 170,
                height: 104,
                borderRadius: 12,
                background: PANEL,
                border: `2px solid ${probColor(c.p)}`,
              }}
            >
              <div style={{ fontSize: 28, color: INK2, fontWeight: 600 }}>{c.label}</div>
              <div style={{ fontSize: 44, fontWeight: 700, color: probColor(c.p) }}>
                {`${Math.round(c.p * 100)}%`}
              </div>
            </div>
          ))}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            marginTop: "auto",
            borderTop: `2px solid ${LINE}`,
            paddingTop: 18,
          }}
        >
          <div style={{ display: "flex", fontSize: 28, color: INK3 }}>
            Democratic win probability
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            {gb ? (
              <div style={{ display: "flex", fontSize: 34, fontWeight: 700 }}>
                {`Generic ballot D+${gb.margin_pp.toFixed(1)}`}
              </div>
            ) : (
              <div style={{ display: "flex", fontSize: 34, color: INK3 }}>
                Generic ballot pending
              </div>
            )}
            <div style={{ display: "flex", fontSize: 28, color: INK2, marginTop: 4 }}>
              {days != null ? `${days} days to ${meta.election_date}` : meta.election_date}
            </div>
          </div>
        </div>
      </div>
    ),
    SIZE,
  );
}
