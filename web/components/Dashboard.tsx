"use client";

import { useMemo, useState } from "react";
import DelegationStrip from "@/components/DelegationStrip";
import EvidenceBars from "@/components/EvidenceBars";
import ForestPlot from "@/components/ForestPlot";
import PartySpread from "@/components/PartySpread";
import TargetProfiles from "@/components/TargetProfiles";
import type { Deviation, Member, Meta, Party, Score } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";

const fmt = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);

function median(vals: number[]): number | undefined {
  if (!vals.length) return undefined;
  const s = [...vals].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export default function Dashboard({
  scores,
  deviations,
  meta,
  delegation,
}: {
  scores: Score[];
  deviations: Deviation[];
  meta: Meta;
  delegation: Member[];
}) {
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
  const [focusId, setFocusId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  const partyBaselines = useMemo(() => {
    const byTheme = scores.filter((s) => s.theme === theme && s.sufficient);
    return {
      Democrat: median(byTheme.filter((s) => s.party === "Democrat").map((s) => s.signed_score)),
      Republican: median(
        byTheme.filter((s) => s.party === "Republican").map((s) => s.signed_score),
      ),
    };
  }, [scores, theme]);

  const selectMember = (id: string) => {
    setSelectedId((prev) => (prev === id ? null : id));
    if (flagged.has(id)) {
      setExpanded(id);
    }
  };

  const linked = {
    focusId,
    selectedId,
    onHover: setFocusId,
    onSelect: selectMember,
  };

  return (
    <section className="section" aria-labelledby="scorecard-heading">
      <h2 id="scorecard-heading" className="sec-title">
        Signed climate scores
      </h2>
      <p className="sec-lede">
        One number per member and theme: share of contested votes that advanced the small-business
        / affordability axis, mapped to [&minus;1, +1]. Hover links charts; click a member to select
        them across the page.
      </p>

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
        <span style={{ color: "var(--ink3)" }}>hover = linked · click = select</span>
      </div>
      <p className="cap">
        {themeLabel(theme)} · {rows.length} members with ≥ {meta.sufficient_min} contested votes ·
        map {meta.map_version}
        {selectedId ? " · member selected" : ""}
      </p>

      {rows.length > 0 ? (
        <ForestPlot
          rows={rows}
          flagged={flagged}
          partyBaselines={partyBaselines}
          {...linked}
        />
      ) : (
        <p className="cap">No members clear the threshold for this filter.</p>
      )}

      <div className="viz-block">
        <h3 className="viz-title">Party spread</h3>
        <p className="viz-lede">
          Same theme, D and R on separate lanes — caucus width, not just the median.
        </p>
        <PartySpread rows={rows} theme={theme} flagged={flagged} {...linked} />
      </div>

      <div className="viz-block">
        <h3 className="viz-title">Delegation strip</h3>
        <p className="viz-lede">
          District order for the active theme. Target seats marked in gold. Click any seat to
          select.
        </p>
        <DelegationStrip
          scores={scores}
          theme={theme}
          delegation={delegation}
          flagged={flagged}
          {...linked}
        />
      </div>

      <div className="viz-block">
        <h3 className="viz-title">Target seats vs caucus</h3>
        <p className="viz-lede">
          VA-1 / VA-2 across every sufficient theme. Dot = member · tick = party median. Click a
          theme row to jump the forest plot.
        </p>
        <TargetProfiles
          scores={scores}
          themes={themes}
          delegation={delegation}
          onThemeSelect={(t) => {
            setTheme(t);
            setExpanded(null);
          }}
          {...linked}
        />
      </div>

      <div className="viz-block">
        <h3 className="viz-title">Evidence density</h3>
        <p className="viz-lede">
          Contested member-votes per theme. Thin bars mean wider Wilson bands above.
        </p>
        <EvidenceBars
          scores={scores}
          themes={themes}
          activeTheme={theme}
          onThemeSelect={(t) => {
            setTheme(t);
            setExpanded(null);
          }}
        />
      </div>

      <h2 className="sec-title" style={{ marginTop: "2.4rem" }}>
        Within-party defections
      </h2>
      <p className="sec-lede">
        Deviation from the caucus baseline when at least one roll call shows a crossover. Selecting
        a flagged member from any chart opens their votes here.
      </p>

      {themeDevs.length === 0 ? (
        <p className="cap">No qualifying defections for this filter.</p>
      ) : (
        <div className="defections">
          {themeDevs.map((d) => {
            const open = expanded === d.bioguide_id;
            const lit =
              focusId === d.bioguide_id || selectedId === d.bioguide_id || open;
            return (
              <div key={d.bioguide_id} id={`def-${d.bioguide_id}`}>
                <button
                  type="button"
                  className={`def-row${lit ? " def-row-lit" : ""}`}
                  aria-expanded={open}
                  onMouseEnter={() => setFocusId(d.bioguide_id)}
                  onMouseLeave={() => setFocusId(null)}
                  onClick={() => {
                    setSelectedId(d.bioguide_id);
                    setExpanded(open ? null : d.bioguide_id);
                  }}
                >
                  <div>
                    <p className={`def-who ${d.party === "Democrat" ? "dem" : "rep"}`}>
                      {shortName(d.full_name)}
                    </p>
                    <p className="def-meta">
                      {d.party} · VA-{d.district_number} · {d.defection_votes.length} crossover
                      vote{d.defection_votes.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <p className="def-score">
                    {fmt(d.deviation)}
                    <small>vs caucus {fmt(d.party_baseline)}</small>
                  </p>
                  <span className="def-hint">{open ? "Hide votes" : "Show votes"}</span>
                </button>
                {open && (
                  <ul className="votes">
                    {d.defection_votes.map((v) => (
                      <li key={v.vote_id}>
                        <span className="pos">{v.position}</span> · {v.vote_date} ·{" "}
                        {v.source_link ? (
                          <a
                            href={v.source_link}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {v.bill_id ?? v.vote_id}
                          </a>
                        ) : (
                          (v.bill_id ?? v.vote_id)
                        )}
                        {v.summary ? ` — ${v.summary}` : " — (no adjudicated summary yet)"}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
