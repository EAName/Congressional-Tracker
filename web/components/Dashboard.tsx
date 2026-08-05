"use client";

import { useEffect, useMemo, useState } from "react";
import CompareOverlay from "@/components/CompareOverlay";
import DelegationStrip from "@/components/DelegationStrip";
import EvidenceBars from "@/components/EvidenceBars";
import ForestPlot from "@/components/ForestPlot";
import Module from "@/components/Module";
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
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);

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

  // Keep compare pins valid for the active theme/party filter.
  useEffect(() => {
    const ids = new Set(rows.map((r) => r.bioguide_id));
    if (compareA && !ids.has(compareA)) setCompareA(null);
    if (compareB && !ids.has(compareB)) setCompareB(null);
  }, [rows, compareA, compareB]);

  // Default compare pins: target seats when present in the filtered rows.
  useEffect(() => {
    if (compareA || compareB || rows.length < 2) return;
    const targets = delegation
      .filter((m) => m.is_target)
      .map((m) => m.bioguide_id)
      .filter((id) => rows.some((r) => r.bioguide_id === id));
    if (targets.length >= 2) {
      setCompareA(targets[0]);
      setCompareB(targets[1]);
    }
  }, [theme, party, rows, delegation, compareA, compareB]);

  const selectMember = (id: string) => {
    setSelectedId((prev) => (prev === id ? null : id));
    if (flagged.has(id)) setExpanded(id);
  };

  const linked = {
    focusId,
    selectedId,
    onHover: setFocusId,
    onSelect: selectMember,
  };

  const pinFromSelection = () => {
    if (!selectedId) return;
    if (!compareA) setCompareA(selectedId);
    else if (!compareB && selectedId !== compareA) setCompareB(selectedId);
    else if (selectedId !== compareA) setCompareB(selectedId);
  };

  return (
    <div className="module-grid">
      <Module
        title="Controls"
        kicker="Theme and party filter every module below"
        span={12}
      >
        <div className="controls" style={{ border: 0, marginBottom: 0 }}>
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
        <div className="legend" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
          <span>
            <i style={{ background: "var(--dem)" }} /> Democrat
          </span>
          <span>
            <i style={{ background: "var(--rep)" }} /> Republican
          </span>
          <span>
            <i style={{ background: "var(--flag)" }} /> crossed caucus
          </span>
          <span style={{ color: "var(--ink3)" }}>
            {themeLabel(theme)} · {rows.length} sufficient
          </span>
        </div>
      </Module>

      <Module
        title="Compare"
        kicker="Pin two members · overlay Wilson intervals"
        span={12}
        action={
          selectedId ? (
            <button type="button" className="tab" onClick={pinFromSelection}>
              Pin selection
            </button>
          ) : null
        }
      >
        <CompareOverlay
          rows={rows}
          memberA={compareA}
          memberB={compareB}
          onChangeA={setCompareA}
          onChangeB={setCompareB}
        />
      </Module>

      <Module
        title="Forest plot"
        kicker="Signed score with 95% Wilson band · hover links modules"
        span={12}
      >
        {rows.length > 0 ? (
          <ForestPlot rows={rows} flagged={flagged} partyBaselines={partyBaselines} {...linked} />
        ) : (
          <p className="cap">No members clear the threshold for this filter.</p>
        )}
      </Module>

      <Module title="Party spread" kicker="Caucus width on this theme" span={6}>
        <PartySpread rows={rows} theme={theme} flagged={flagged} {...linked} />
      </Module>

      <Module title="Delegation strip" kicker="District order · gold = targets" span={6}>
        <DelegationStrip
          scores={scores}
          theme={theme}
          delegation={delegation}
          flagged={flagged}
          {...linked}
        />
      </Module>

      <Module
        title="Target seats vs caucus"
        kicker="VA-1 / VA-2 across themes · tick = party median"
        span={8}
      >
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
      </Module>

      <Module title="Evidence density" kicker="Click a bar to change theme" span={4}>
        <EvidenceBars
          scores={scores}
          themes={themes}
          activeTheme={theme}
          onThemeSelect={(t) => {
            setTheme(t);
            setExpanded(null);
          }}
        />
      </Module>

      <Module
        title="Within-party defections"
        kicker="Selecting a flagged member from any chart opens their votes"
        span={12}
      >
        {themeDevs.length === 0 ? (
          <p className="cap">No qualifying defections for this filter.</p>
        ) : (
          <div className="defections">
            {themeDevs.map((d) => {
              const open = expanded === d.bioguide_id;
              const lit = focusId === d.bioguide_id || selectedId === d.bioguide_id || open;
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
      </Module>
    </div>
  );
}
