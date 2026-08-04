"use client";

import { useMemo } from "react";
import type { Score } from "@/lib/types";
import { themeLabel } from "@/lib/types";

const W = 720;
const H = 220;
const PAD_L = 128;
const PAD_R = 24;
const PAD_T = 16;
const PAD_B = 48;

export default function EvidenceBars({
  scores,
  themes,
  activeTheme,
  onThemeSelect,
}: {
  scores: Score[];
  themes: string[];
  activeTheme?: string;
  onThemeSelect?: (theme: string) => void;
}) {
  const bars = useMemo(() => {
    return themes.map((theme) => {
      const cells = scores.filter((s) => s.theme === theme && s.sufficient);
      const memberVotes = cells.reduce((acc, s) => acc + s.n_contested, 0);
      const members = cells.length;
      return { theme, memberVotes, members };
    });
  }, [scores, themes]);

  const max = Math.max(1, ...bars.map((b) => b.memberVotes));
  const innerW = W - PAD_L - PAD_R;
  const innerH = H - PAD_T - PAD_B;
  const gap = 10;
  const barW = Math.max(18, (innerW - gap * (bars.length - 1)) / Math.max(bars.length, 1));

  return (
    <div className="viz-frame">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Contested member-votes by theme">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = PAD_T + innerH * (1 - t);
          const val = Math.round(max * t);
          return (
            <g key={t}>
              <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="var(--line)" strokeWidth={1} />
              <text x={PAD_L - 8} y={y + 3} textAnchor="end" fontSize={10} fill="var(--ink3)">
                {val}
              </text>
            </g>
          );
        })}

        {bars.map((b, i) => {
          const h = (b.memberVotes / max) * innerH;
          const x = PAD_L + i * (barW + gap);
          const y = PAD_T + innerH - h;
          const active = b.theme === activeTheme;
          return (
            <g
              key={b.theme}
              style={{ cursor: onThemeSelect ? "pointer" : "default" }}
              onClick={() => onThemeSelect?.(b.theme)}
            >
              <rect
                x={x}
                y={y}
                width={barW}
                height={Math.max(h, 2)}
                rx={3}
                fill={active ? "var(--navy)" : "var(--dem)"}
                opacity={active ? 1 : 0.78}
              />
              <text
                x={x + barW / 2}
                y={y - 6}
                textAnchor="middle"
                fontSize={10}
                fontWeight={600}
                fill="var(--ink)"
              >
                {b.memberVotes}
              </text>
              <text
                x={x + barW / 2}
                y={H - 22}
                textAnchor="middle"
                fontSize={9.5}
                fontWeight={active ? 700 : 500}
                fill={active ? "var(--navy)" : "var(--ink2)"}
              >
                {themeLabel(b.theme)}
              </text>
              <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize={9} fill="var(--ink3)">
                {b.members} mbrs
              </text>
            </g>
          );
        })}
      </svg>
      <p className="scale-cap">
        Sum of contested Yea/Nay tallies across members with a sufficient cell in that theme
        (member-votes, not unique roll calls).
      </p>
    </div>
  );
}
