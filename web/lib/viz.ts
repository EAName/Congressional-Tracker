/** Diverging color for signed score ∈ [-1, 1] → anti-axis … pro-axis. */
export function scoreFill(score: number, alpha = 1): string {
  const t = Math.max(-1, Math.min(1, score));
  if (t >= 0) {
    // navy → dem blue
    const a = t;
    const r = Math.round(16 + (31 - 16) * a);
    const g = Math.round(24 + (91 - 24) * a);
    const b = Math.round(32 + (181 - 32) * a);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  // flag/bronze → rep red
  const a = -t;
  const r = Math.round(154 + (180 - 154) * a);
  const g = Math.round(103 + (35 - 103) * a);
  const b = Math.round(0 + (24 - 0) * a);
  return `rgba(${r},${g},${b},${alpha})`;
}

export const fmtScore = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2);
