"use client";

import { useMemo, useState } from "react";
import type { Member, PartyBaseline, Score, ScoreMode } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { estimate, fmtScore } from "@/lib/viz";

const ROW_H = 28;
const LABEL_W = 150;
const AXIS_W = 220;
const PAD = 12;

function caucusTick(
  baselines: PartyBaseline[] | undefined,
  theme: string,
  party: string | null,
  mode: ScoreMode,
): number | undefined {
  if (!party || !baselines) return undefined;
  const b = baselines.find((x) => x.theme === theme && x.party === party);
  if (!b) return undefined;
  if (mode === "eb") return b.eb_center;
  return b.weighted_median ?? undefined;
}

export default function TargetProfiles({
  scores,
  themes,
  delegation,
  focusId,
  selectedId,
  onHover,
  onSelect,
  onThemeSelect,
  mode = "eb",
  baselines,
}: {
  scores: Score[];
  themes: string[];
  delegation: Member[];
  focusId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  onThemeSelect: (theme: string) => void;
  mode?: ScoreMode;
  baselines?: PartyBaseline[];
}) {
  const [tip, setTip] = useState<{
    text: string;
    x: number;
    y: number;
  } | null>(null);

  const targets = useMemo(
    () =>
      delegation
        .filter((m) => m.is_target && m.chamber === "House")
        .sort((a, b) => (a.district_number ?? 0) - (b.district_number ?? 0)),
    [delegation],
  );

  if (!targets.length) return null;

  const H = PAD * 2 + themes.length * ROW_H + 28;
  const panelW = LABEL_W + AXIS_W + 24;
  const W = targets.length * panelW + 8;
  const xScore = (v: number) => LABEL_W + ((Math.max(-1, Math.min(1, v)) + 1) / 2) * AXIS_W;
  const active = focusId ?? selectedId;

  return (
    <div className="viz-frame">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label="Target seat scores versus caucus center across themes"
      >
        {targets.map((m, ti) => {
          const ox = ti * panelW;
          const isActive = active === m.bioguide_id;
          return (
            <g
              key={m.bioguide_id}
              opacity={active != null && !isActive ? 0.35 : 1}
              className="viz-hit"
              style={{ cursor: "pointer" }}
              onMouseEnter={() => onHover(m.bioguide_id)}
              onMouseLeave={() => onHover(null)}
              onClick={() => onSelect(m.bioguide_id)}
            >
              <rect
                x={ox + 4}
                y={4}
                width={panelW - 8}
                height={H - 8}
                fill={selectedId === m.bioguide_id ? "var(--dem-soft)" : "var(--paper)"}
                stroke={selectedId === m.bioguide_id ? "var(--navy)" : "var(--line)"}
                rx={4}
              />
              <text x={ox + 16} y={22} fontSize={13} fontWeight={700} fill="var(--navy)">
                VA-{m.district_number} · {shortName(m.full_name)}
              </text>
              <text x={ox + 16} y={36} fontSize={10} fill="var(--ink3)">
                vs {m.party} caucus {mode === "eb" ? "EB center" : "weighted median"} (tick)
              </text>

              {themes.map((theme, i) => {
                const cell = scores.find(
                  (s) =>
                    s.bioguide_id === m.bioguide_id && s.theme === theme && s.sufficient,
                );
                const est = cell ? estimate(cell, mode) : null;
                const y = 48 + i * ROW_H;
                const med = caucusTick(baselines, theme, m.party, mode);
                return (
                  <g
                    key={theme}
                    onClick={(e) => {
                      e.stopPropagation();
                      onThemeSelect(theme);
                      onSelect(m.bioguide_id);
                    }}
                    onMouseEnter={(e) => {
                      onHover(m.bioguide_id);
                      const scoreTxt = est
                        ? `${fmtScore(est.value)} (n=${est.n})`
                        : "insufficient";
                      const medTxt = med != null ? fmtScore(med) : "—";
                      setTip({
                        text: `${themeLabel(theme)}: member ${scoreTxt} · caucus ${medTxt}`,
                        x: e.clientX,
                        y: e.clientY,
                      });
                    }}
                    onMouseMove={(e) =>
                      setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))
                    }
                    onMouseLeave={() => setTip(null)}
                  >
                    <text
                      x={ox + 16}
                      y={y + 14}
                      fontSize={10}
                      fill="var(--ink2)"
                      fontWeight={500}
                    >
                      {themeLabel(theme)}
                    </text>
                    <line
                      x1={ox + LABEL_W}
                      y1={y + 10}
                      x2={ox + LABEL_W + AXIS_W}
                      y2={y + 10}
                      stroke="var(--line)"
                    />
                    <line
                      x1={ox + xScore(0)}
                      y1={y + 4}
                      x2={ox + xScore(0)}
                      y2={y + 16}
                      stroke="var(--zero)"
                      strokeWidth={1}
                    />
                    {med != null && (
                      <line
                        x1={ox + xScore(med)}
                        y1={y + 3}
                        x2={ox + xScore(med)}
                        y2={y + 17}
                        stroke="var(--ink3)"
                        strokeWidth={2}
                      />
                    )}
                    {est && (
                      <circle
                        cx={ox + xScore(est.value)}
                        cy={y + 10}
                        r={isActive ? 6.5 : 5}
                        fill="var(--rep)"
                        stroke="var(--surface)"
                        strokeWidth={1.5}
                      />
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <p className="scale-cap">
        Dot = target member {mode === "eb" ? "EB" : "raw"} score · vertical tick = caucus
        {mode === "eb" ? " prior mean" : " weighted median"}. Click a theme row to retarget the
        forest plot; click the panel to select the member.
      </p>
      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          {tip.text}
        </div>
      )}
    </div>
  );
}
