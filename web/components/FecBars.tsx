import type { FecCandidate } from "@/lib/types";

function money(n: number | null) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${n.toFixed(0)}`;
}

export default function FecBars({ candidates }: { candidates: FecCandidate[] }) {
  if (candidates.length === 0) {
    return <p className="cap">No FEC snapshot on disk yet.</p>;
  }
  const max = Math.max(...candidates.map((c) => c.receipts ?? 0), 1);
  return (
    <div className="fec-bars">
      {candidates.map((c) => (
        <div key={c.fec_candidate_id} className="fec-row">
          <div className="fec-name">
            <strong>{c.name}</strong>
            <span>
              {c.role} · {c.party === "Democrat" ? "D" : "R"}
            </span>
          </div>
          <div
            className={`fec-bar ${c.party === "Democrat" ? "dem" : "rep"}`}
            style={{ width: `${((c.receipts ?? 0) / max) * 100}%` }}
          />
          <div className="fec-meta">
            {money(c.receipts)} receipts · {money(c.cash_on_hand)} cash
            {c.small_dollar_share != null ? ` · ${Math.round(c.small_dollar_share * 100)}% small-dollar` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
