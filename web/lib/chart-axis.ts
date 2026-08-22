export type TickAnchor = "start" | "middle" | "end";

export function tickAnchorAtIndex(index: number, count: number): TickAnchor {
  if (count <= 1) return "middle";
  if (index === 0) return "start";
  if (index === count - 1) return "end";
  return "middle";
}

export function clampTickX(
  x: number,
  bounds: { min: number; max: number },
  anchor: TickAnchor,
): number {
  const { min, max } = bounds;
  if (anchor === "start") return Math.max(min, Math.min(x, max));
  if (anchor === "end") return Math.min(max, Math.max(x, min));
  return Math.max(min, Math.min(x, max));
}

/** Drop tick values that would render closer than minGapPx on the x-axis. */
export function filterTicksByGap(
  values: number[],
  xOf: (v: number) => number,
  minGapPx: number,
): number[] {
  const out: number[] = [];
  for (const v of values) {
    if (out.length === 0) {
      out.push(v);
      continue;
    }
    const gap = xOf(v) - xOf(out[out.length - 1]);
    if (gap >= minGapPx) {
      out.push(v);
      continue;
    }
    if (v === values[values.length - 1] && out.length > 0 && out[out.length - 1] !== values[0]) {
      out.pop();
      out.push(v);
    }
  }
  return out;
}

export function formatDayTick(date: string): string {
  const [, m, d] = date.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m) - 1]} ${Number(d)}`;
}

export function timeAxisTicks(
  dates: string[],
  xOf: (date: string) => number,
  minGapPx: number,
): Array<{ date: string; label: string; anchor: TickAnchor }> {
  if (dates.length === 0) return [];
  if (dates.length === 1) {
    return [{ date: dates[0], label: dates[0].slice(0, 7), anchor: "middle" }];
  }

  const last = dates.length - 1;
  const mid = Math.floor(dates.length / 2);
  const indices = filterTicksByGap([0, mid, last], (idx) => xOf(dates[idx]), minGapPx);

  const monthLabels = new Set<string>();
  return indices.map((idx, i) => {
    const date = dates[idx];
    const month = date.slice(0, 7);
    const label = monthLabels.has(month) ? formatDayTick(date) : month;
    monthLabels.add(month);
    return {
      date,
      label,
      anchor: tickAnchorAtIndex(i, indices.length),
    };
  });
}

export function scoreTickLabel(t: number): string {
  return (t > 0 ? "+" : "") + String(t);
}

/** Nudge two y-positions apart when end-of-chart labels would collide. */
export function separateLabelYs(a: number, b: number, minGap: number): [number, number] {
  const gap = Math.abs(a - b);
  if (gap >= minGap) return [a, b];
  const mid = (a + b) / 2;
  const half = minGap / 2;
  return a <= b ? [mid - half, mid + half] : [mid + half, mid - half];
}
