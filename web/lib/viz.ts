import type { Score, ScoreMode } from "@/lib/types";

export const fmtScore = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);

export interface PointEstimate {
  value: number;
  lo: number;
  hi: number;
  kind: "wilson" | "credible";
  n: number;
  k: number;
}

export function estimate(s: Score, mode: ScoreMode): PointEstimate | null {
  if (mode === "eb") {
    return {
      value: s.eb_score,
      lo: s.cred_lo,
      hi: s.cred_hi,
      kind: "credible",
      n: s.n ?? s.n_contested,
      k: s.k ?? s.n_pro ?? 0,
    };
  }
  if (s.raw_score == null && s.signed_score == null) return null;
  const value = s.raw_score ?? s.signed_score;
  const lo = s.wilson_lo ?? s.wilson_low;
  const hi = s.wilson_hi ?? s.wilson_high;
  if (value == null || lo == null || hi == null) return null;
  return {
    value,
    lo,
    hi,
    kind: "wilson",
    n: s.n ?? s.n_contested,
    k: s.k ?? s.n_pro ?? 0,
  };
}
