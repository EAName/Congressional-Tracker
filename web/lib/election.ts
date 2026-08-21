/** Election-day calendar math for the public site (Virginia = America/New_York). */

const TZ = "America/New_York";

/** Civil YYYY-MM-DD in America/New_York for an instant. */
export function civilDateInVirginia(instant: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instant);
}

function parseIsoDate(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) {
    throw new Error(`expected YYYY-MM-DD, got ${JSON.stringify(iso)}`);
  }
  return { y, m, d };
}

/**
 * Whole calendar days from today's Virginia civil date to election_date.
 * Negative after election day. Independent of export-time meta.json.
 */
export function daysUntilElection(electionDate: string, asOf: Date = new Date()): number {
  const election = parseIsoDate(electionDate);
  const today = parseIsoDate(civilDateInVirginia(asOf));
  const electionUtc = Date.UTC(election.y, election.m - 1, election.d);
  const todayUtc = Date.UTC(today.y, today.m - 1, today.d);
  return Math.round((electionUtc - todayUtc) / 86_400_000);
}

export function formatElectionCountdown(
  electionDate: string,
  asOf: Date = new Date(),
): string {
  const days = daysUntilElection(electionDate, asOf);
  if (days > 0) return `${days} days to ${electionDate}`;
  if (days === 0) return "Election day";
  return `${Math.abs(days)} days since ${electionDate}`;
}
