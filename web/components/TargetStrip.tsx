import type { Member } from "@/lib/types";
import { shortName } from "@/lib/types";

export default function TargetStrip({ members }: { members: Member[] }) {
  const targets = members
    .filter((m) => m.is_target && m.chamber === "House")
    .sort((a, b) => (a.district_number ?? 0) - (b.district_number ?? 0));

  if (targets.length === 0) return null;

  return (
    <div className="targets" aria-label="2021 map target seats">
      {targets.map((m) => (
        <div key={m.bioguide_id} className="target">
          <p className="target-kicker">Target seat · VA-{m.district_number}</p>
          <p className="target-name">{shortName(m.full_name)}</p>
          <p className="target-meta">
            {m.party} · 2021 court-drawn map
          </p>
          {m.partisan_lean ? <span className="target-lean">{m.partisan_lean}</span> : null}
        </div>
      ))}
    </div>
  );
}
