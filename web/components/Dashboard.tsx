"use client";

import { useMemo, useState } from "react";
import ForestPlot from "@/components/ForestPlot";
import type { Deviation, Meta, Party, Score } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";

const fmt = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);

export default function Dashboard({
  scores,
  deviations,
  meta,
}: {
  scores: Score[];
  deviations: Deviation[];
  meta: Meta;
}) {
  // Only themes with at least one sufficient member are worth charting.
  const themes = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of scores) {
      if (s.sufficient) counts.set(s.theme, (counts.get(s.theme) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }, [scores]);

  const [theme, setTheme] = useState(themes[0] ?? meta.themes[0]);
  const [party, setParty] = useState<Party | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      scores.filter(
        (s) => s.theme === theme && s.sufficient && (party === "all" || s.party === party),
      ),
    [scores, theme, party],
  );

  const themeDevs = useMemo(
    () =>
      deviations
        .filter((d) => d.theme === theme && (party === "all" || d.party === party))
        .sort((a, b) => Math.abs(b.deviation) - Math.abs(a.deviation)),
    [deviations, theme, party],
  );

  const flagged = useMemo(() => new Set(themeDevs.map((d) => d.bioguide_id)), [themeDevs]);

  return (
    <>
      <div className="controls">
        <div className="tabs" role="tablist" aria-label="Theme">
          {themes.map((t) => (
            <button
              key={t}
              className="tab"
              role="tab"
              aria-pressed={t === theme}
              onClick={() => {
                setTheme(t);
                setExpanded(null);
              }}
            >
              {themeLabel(t)}
            </button>
          ))}
        </div>
        <span className="spacer" />
        <div className="seg" role="group" aria-label="Party filter">
          {(["all", "Democrat", "Republican"] as const).map((p) => (
            <button key={p} aria-pressed={party === p} onClick={() => setParty(p)}>
              {p === "all" ? "All" : p === "Democrat" ? "Dem" : "Rep"}
            </button>
          ))}
        </div>
      </div>

      <div className="legend">
        <span>
          <i style={{ background: "var(--dem)" }} /> Democrat
        </span>
        <span>
          <i style={{ background: "var(--rep)" }} /> Republican
        </span>
        <span>
          <i style={{ background: "var(--flag)" }} /> crossed their caucus
        </span>
      </div>
      <p className="cap">
        {themeLabel(theme)} &middot; {rows.length} members with &ge; {meta.sufficient_min} contested
        votes
      </p>

      {rows.length > 0 ? (
        <ForestPlot rows={rows} flagged={flagged} onSelect={(b) => setExpanded(b)} />
      ) : (
        <p className="cap">No members clear the threshold for this filter.</p>
      )}

      <h2 className="sec-h">Within-party defections</h2>
      <p className="sec-s">
        Members whose deviation from their caucus baseline is backed by specific crossover votes.
        Click a card for the votes.
      </p>
      {themeDevs.length === 0 ? (
        <p className="cap">No qualifying defections for this filter.</p>
      ) : (
        <div className="cards">
          {themeDevs.map((d) => {
            const open = expanded === d.bioguide_id;
            return (
              <div
                key={d.bioguide_id}
                className="card"
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : d.bioguide_id)}
              >
                <p className="who" style={{ color: d.party === "Democrat" ? "var(--dem)" : "var(--rep)" }}>
                  {shortName(d.full_name)}
                </p>
                <p className="meta">
                  {d.party} &middot; VA-{d.district_number} &middot; {d.defection_votes.length}{" "}
                  crossover vote{d.defection_votes.length > 1 ? "s" : ""}
                </p>
                <p className="big">
                  {fmt(d.deviation)}
                  <small>vs caucus {fmt(d.party_baseline)}</small>
                </p>
                {open && (
                  <ul className="votes">
                    {d.defection_votes.map((v) => (
                      <li key={v.vote_id}>
                        <span className="pos">{v.position}</span> &middot; {v.vote_date} &middot;{" "}
                        {v.source_link ? (
                          <a href={v.source_link} target="_blank" rel="noreferrer">
                            {v.bill_id ?? v.vote_id}
                          </a>
                        ) : (
                          (v.bill_id ?? v.vote_id)
                        )}
                        {v.summary ? ` — ${v.summary}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
