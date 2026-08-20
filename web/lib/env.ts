/** Client-side lookup on the build-time environment grid. No network. */

export function interpolateGrid(margins: number[], values: number[], x: number): number {
  if (values.length !== margins.length || margins.length === 0) return values[0] ?? 0;
  if (x <= margins[0]) return values[0];
  if (x >= margins[margins.length - 1]) return values[values.length - 1];
  for (let i = 0; i < margins.length - 1; i += 1) {
    const lo = margins[i];
    const hi = margins[i + 1];
    if (x >= lo && x <= hi) {
      if (hi === lo) return values[i];
      const t = (x - lo) / (hi - lo);
      return values[i] + t * (values[i + 1] - values[i]);
    }
  }
  return values[values.length - 1];
}

export function formatMargin(pp: number): string {
  const sign = pp > 0 ? "+" : "";
  return `D${sign}${pp}`;
}
