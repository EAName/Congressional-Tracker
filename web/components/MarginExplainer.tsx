"use client";

import { formatMargin } from "@/lib/env";
import type { GenericBallotInput } from "@/lib/types";

const tenth = (x: number) => Math.round(x * 10) / 10;
const one = (x: number) => x.toFixed(1);

/**
 * How the slider's current average comes out of the poll average: set undecided
 * voters aside and split the rest between the parties. Every figure is this
 * week's data, not a worked example.
 *
 * Each line is computed from the one-decimal figures it displays, so every
 * division and subtraction a reader checks is literally true. That can leave the
 * result a tenth off the slider, which is computed from unrounded shares, and the
 * note says so.
 */
export default function MarginExplainer({
  generic,
  current,
}: {
  generic: GenericBallotInput;
  /** The slider's current average, already formatted, e.g. "D+7.8". */
  current: string;
}) {
  if (generic.dem == null || generic.rep == null) return null;
  const dem = tenth(generic.dem * 100);
  const rep = tenth(generic.rep * 100);
  const decided = tenth(dem + rep);
  if (decided <= 0) return null;
  const undecided = tenth(100 - decided);
  const demTwo = tenth((dem / decided) * 100);
  const repTwo = tenth((rep / decided) * 100);
  const margin = tenth(demTwo - repTwo);

  return (
    <details className="margin-explainer">
      <summary>How {current} is calculated</summary>
      <div className="margin-explainer-body">
        <p>
          The poll average has Democrats at {one(dem)}% and Republicans at {one(rep)}%, with{" "}
          {one(undecided)}% undecided or choosing someone else.
        </p>
        <p>
          Set the undecideds aside, and {one(decided)}% of voters remain. Split that{" "}
          {one(decided)}% between the parties:
        </p>
        <dl className="margin-explainer-math">
          <div className="is-dem">
            <dt>Democrats</dt>
            <dd>
              {one(dem)} ÷ {one(decided)} = {one(demTwo)}%
            </dd>
          </div>
          <div className="is-rep">
            <dt>Republicans</dt>
            <dd>
              {one(rep)} ÷ {one(decided)} = {one(repTwo)}%
            </dd>
          </div>
          <div className="is-total">
            <dt>Margin</dt>
            <dd>
              {one(demTwo)} − {one(repTwo)} = {formatMargin(margin)}
            </dd>
          </div>
        </dl>
        <p className="margin-explainer-note">
          Elections have no undecided option, so the forecasts use this two-party margin. That
          assumes undecided voters split the way decided voters already have. The generic ballot
          chart&rsquo;s margin is smaller because it keeps undecided voters in the count. Figures are
          rounded to one decimal, so the result can differ from the slider by a tenth.
        </p>
      </div>
    </details>
  );
}
