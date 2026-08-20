import type { DisclosureDoc } from "@/lib/types";
import disclosureJson from "@/data/disclosure.json";

const doc = disclosureJson as DisclosureDoc;

export default function RaceDisclaimer({ raceId }: { raceId: string }) {
  const text =
    doc.race_page.by_race_id[raceId]?.trim() || doc.race_page.default_disclaimer.trim();
  if (!text) return null;
  return (
    <aside className="race-disclaimer" aria-label="Race page disclaimer">
      <p>{text}</p>
    </aside>
  );
}
