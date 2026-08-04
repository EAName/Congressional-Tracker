"use client";

import { useMemo, useState } from "react";
import type { Score } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { fmtScore, scoreFill } from "@/lib/viz";

const CELL_W = 72;
const CELL_H = 28;
const LABEL_W = 150;
const HEAD_H = 64;

export default function ScoreHeatmap({
  scores,
  themes,
  onThemeSelect,
}: {
  scores: Score[];
  themes: string[];
  onThemeSelect?: (theme: string) => void;
}) {
  const [hover, setHover] = useState<{ score: Score; x: number; y: number } | null>(null);

  const { members, lookup } = useMemo(() => {
    const byBio = new Map<string, { name: string; party: string | null; district: number | null; chamber: string }>();
    const map = new Map<string, Score>();
    for (const s of scores) {
      if (!s.sufficient) continue;
      map.set(`${s.bioguide_id}::${s.theme}`, s);
      byBio.set(s.bioguide_id, {
        name: s.full_name,
        party: s.party,
        district: s.district_number,
        chamber: s.chamber,
      });
    }
    const members = [...byBio.entries()]
      .map(([bioguide_id, m]) => ({ bioguide_id, ...m }))
      .sort((a, b) => {
        const da = a.district ?? 100;
        const db = b.district ?? 100;
        if (da !== db) return da - db;
        return a.name.localeCompare(b.name);
      });
    return { members, lookup: map };
  }, [scores]);

  if (!themes.length || !members.length) {
    return <p className="cap">Not enough sufficient cells for a heatmap.</p>;
  }

  const W = LABEL_W + themes.length * CELL_W + 8;
  const H = HEAD_H + members.length * CELL_H + 8;

  return (
    <div className="viz-frame">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label="Heatmap of signed scores by member and theme"
        className="heatmap-svg"
      >
        {themes.map((t, j) => (
          <g key={t}>
            <text
              x={LABEL_W + j * CELL_W + CELL_W / 2}
              y={HEAD_H - 14}
              textAnchor="middle"
              fontSize={10}
              fontWeight={600}
              fill="var(--ink2)"
              transform={`rotate(-28 ${LABEL_W + j * CELL_W + CELL_W / 2} ${HEAD_H - 14})`}
              style={{ cursor: onThemeSelect ? "pointer" : "default" }}
              onClick={() => onThemeSelect?.(t)}
            >
              {themeLabel(t)}
            </text>
          </g>
        ))}

        {members.map((m, i) => {
          const y = HEAD_H + i * CELL_H;
          return (
            <g key={m.bioguide_id}>
              <text x={LABEL_W - 10} y={y + CELL_H / 2 + 4} textAnchor="end" fontSize={11.5} fill="var(--ink)">
                {shortName(m.name)}
              </text>
              <text x={LABEL_W - 10} y={y + CELL_H / 2 + 15} textAnchor="end" fontSize={9} fill="var(--ink3)">
                {m.district != null ? `VA-${m.district}` : m.chamber}
              </text>
              {themes.map((t, j) => {
                const cell = lookup.get(`${m.bioguide_id}::${t}`);
                const x = LABEL_W + j * CELL_W;
                if (!cell) {
                  return (
                    <rect
                      key={t}
                      x={x + 2}
                      y={y + 3}
                      width={CELL_W - 4}
                      height={CELL_H - 6}
                      fill="var(--paper)"
                      stroke="var(--line)"
                      strokeWidth={1}
                    />
                  );
                }
                return (
                  <rect
                    key={t}
                    x={x + 2}
                    y={y + 3}
                    width={CELL_W - 4}
                    height={CELL_H - 6}
                    rx={2}
                    fill={scoreFill(cell.signed_score)}
                    style={{ cursor: onThemeSelect ? "pointer" : "default" }}
                    onMouseEnter={(e) => setHover({ score: cell, x: e.clientX, y: e.clientY })}
                    onMouseMove={(e) => setHover({ score: cell, x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onThemeSelect?.(t)}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>
      <p className="scale-cap">
        <span style={{ color: scoreFill(-1) }}>−1 opposed</span>
        <span> · </span>
        <span style={{ color: scoreFill(1) }}>+1 advanced</span>
        <span> · empty = insufficient contested votes · click a column to focus the forest plot</span>
      </p>

      {hover && (
        <div className="tooltip" style={{ left: hover.x, top: hover.y }}>
          <strong>
            {shortName(hover.score.full_name)} · {themeLabel(hover.score.theme)}
          </strong>
          {fmtScore(hover.score.signed_score)} · n={hover.score.n_contested}
        </div>
      )}
    </div>
  );
}
