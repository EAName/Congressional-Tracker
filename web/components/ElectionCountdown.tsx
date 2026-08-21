"use client";

import { useEffect, useState } from "react";
import { formatElectionCountdown } from "@/lib/election";

/**
 * Countdown from Virginia civil date to election_date.
 * Client-side so it advances daily without redeploying export JSON.
 */
export default function ElectionCountdown({
  electionDate,
  className = "election-countdown",
}: {
  electionDate: string;
  className?: string;
}) {
  const [label, setLabel] = useState(() => formatElectionCountdown(electionDate));

  useEffect(() => {
    const tick = () => setLabel(formatElectionCountdown(electionDate));
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => window.clearInterval(id);
  }, [electionDate]);

  return <p className={className}>{label}</p>;
}
