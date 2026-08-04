import Dashboard from "@/components/Dashboard";
import type { Deviation, Meta, Score } from "@/lib/types";
import deviationsJson from "@/data/deviations.json";
import metaJson from "@/data/meta.json";
import scoresJson from "@/data/scores.json";

export default function Page() {
  const scores = scoresJson as unknown as Score[];
  const deviations = deviationsJson as unknown as Deviation[];
  const meta = metaJson as unknown as Meta;

  return (
    <main className="wrap">
      <h1 className="h1">Virginia delegation — small-business climate scorecard</h1>
      <p className="sub">
        Each member&rsquo;s signed score per theme, from <strong>&minus;1</strong> (consistently
        opposed the small-business / affordability axis) to <strong>+1</strong> (consistently
        advanced it). The line is the 95% Wilson interval &mdash; honest uncertainty given how few
        votes each rests on. Hover a point for detail; click a defector to see the votes that drove
        their break with the caucus.
      </p>
      <Dashboard scores={scores} deviations={deviations} meta={meta} />
      <footer>
        Signed score = 2&middot;(share of contested votes advancing the axis) &minus; 1, over
        scoring-representative passage votes with an adjudicated valence. Bands are 95% Wilson
        intervals. Operative 2021 court-drawn map. Generated {meta.generated_at_utc} from live
        warehouse data; procedural, nomination, and un-adjudicated votes excluded.
      </footer>
    </main>
  );
}
