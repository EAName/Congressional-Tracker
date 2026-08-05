"use client";

import { useMemo, useState } from "react";
import type { Member, Score } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { fmtScore } from "@/lib/viz";

const W = 720;
const H = 168;
const PAD_L = 20;
const PAD_R = 20;
const PAD_T = 36;
const PAD_B = 44;

export default function DelegationStrip({
  scores,
  theme,
  delegation,
  flagged,
  focusId,
  selectedId,
  onHover,
  onSelect,
}: {
  scores: Score[];
  theme: string;
  delegation: Member[];
  flagged: Set<string>;
  focusId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const [tip, setTip] = useState<{ score: Score | null; member: Member; x: number; y: number } | null>(
    null,
  );

  const slots = useMemo(() => {
    const house = delegation
      .filter((m) => m.chamber === "House")
      .sort((a, b) => (a.district_number ?? 0) - (b.district_number ?? 0));
    const senate = delegation.filter((m) => m.chamber === "Senate");
    return [...house, ...senate];
  }, [delegation]);

  const byBio = useMemo(() => {
    const map = new Map<string, Score>();
    for (const s of scores) {
      if (s.theme === theme && s.sufficient) map.set(s.bioguide_id, s);
    }
    return map;
  }, [scores, theme]);

  if (!slots.length) return null;

  const innerW = W - PAD_L - PAD_R;
  const step = innerW / slots.length;
  const yScore = (v: number) =>
    PAD_T + ((1 - Math.max(-1, Math.min(1, v))) / 2) * (H - PAD_T - PAD_B);
  const active = focusId ?? selectedId;

  return (
    <div className="viz-frame">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Delegation strip for ${themeLabel(theme)}`}
      >
        <line
          x1={PAD_L}
          y1={yScore(0)}
          x2={W - PAD_R}
          y2={yScore(0)}
          stroke="var(--navy)"
          strokeWidth={1.2}
          opacity={0.35}
        />
        <text x={PAD_L} y={14} fontSize={10} fill="var(--ink3)">
          +1
        </text>
        <text x={PAD_L} y={H - 28} fontSize={10} fill="var(--ink3)">
          −1
        </text>

        {slots.map((m, i) => {
          const cx = PAD_L + step * i + step / 2;
          const score = byBio.get(m.bioguide_id) ?? null;
          const isActive = active === m.bioguide_id;
          const isSelected = selectedId === m.bioguide_id;
          const isFlag = flagged.has(m.bioguide_id);
          const color = !score
            ? "var(--line-strong)"
            : isFlag
              ? "var(--flag)"
              : m.party === "Democrat"
                ? "var(--dem)"
                : "var(--rep)";
          const cy = score ? yScore(score.signed_score) : yScore(0);
          return (
            <g
              key={m.bioguide_id}
              className="viz-hit"
              opacity={active != null && !isActive ? 0.25 : 1}
              style={{ cursor: "pointer" }}
              onMouseEnter={(e) => {
                onHover(m.bioguide_id);
                setTip({ score, member: m, x: e.clientX, y: e.clientY });
              }}
              onMouseMove={(e) => setTip({ score, member: m, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => {
                onHover(null);
                setTip(null);
              }}
              onClick={() => onSelect(m.bioguide_id)}
            >
              <line
                x1={cx}
                y1={PAD_T}
                x2={cx}
                y2={H - PAD_B}
                stroke="var(--line)"
                strokeWidth={1}
              />
              <circle
                cx={cx}
                cy={cy}
                r={score ? (isActive ? 8 : 6) : 3.5}
                fill={color}
                stroke={isSelected ? "var(--navy)" : "var(--surface)"}
                strokeWidth={isSelected ? 2.4 : 1.4}
              />
              <text
                x={cx}
                y={H - 14}
                textAnchor="middle"
                fontSize={9}
                fontWeight={m.is_target || isSelected ? 700 : 500}
                fill={m.is_target ? "var(--flag)" : "var(--ink3)"}
              >
                {m.district_number != null ? m.district_number : "S"}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="scale-cap">
        District order 1–11, then Senate (S). Gold labels = 2021 target seats. Empty/small dots =
        insufficient for {themeLabel(theme)}.
      </p>
      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          <strong>
            {shortName(tip.member.full_name)}
            {tip.member.district_number != null
              ? ` · VA-${tip.member.district_number}`
              : " · Senate"}
          </strong>
          {tip.score
            ? `${fmtScore(tip.score.signed_score)} · Wilson [${fmtScore(tip.score.wilson_low)}, ${fmtScore(tip.score.wilson_high)}] · n=${tip.score.n_contested}`
            : "No sufficient cell in this theme"}
          {tip.member.is_target ? " · target seat" : ""}
        </div>
      )}
    </div>
  );
}
