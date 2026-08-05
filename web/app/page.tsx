import Dashboard from "@/components/Dashboard";
import TargetStrip from "@/components/TargetStrip";
import type { Deviation, Member, Meta, Score } from "@/lib/types";
import delegationJson from "@/data/delegation.json";
import deviationsJson from "@/data/deviations.json";
import metaJson from "@/data/meta.json";
import scoresJson from "@/data/scores.json";

export default function Page() {
  const scores = scoresJson as Score[];
  const deviations = deviationsJson as Deviation[];
  const meta = metaJson as Meta;
  const delegation = delegationJson as Member[];

  return (
    <div className="shell">
      <header className="hero">
        <div className="hero-inner">
          <p className="product">Congressional Vote Tracker</p>
          <h1 className="brand">Democrats for Virginia</h1>
          <p className="lede">
            Where the Virginia delegation stands on the small-business and affordability axis — with
            honest uncertainty, within-party breaks called out, and every claim tied to an official
            roll call.
          </p>
          <div className="hero-meta">
            <span>
              Map <strong>{meta.map_version} court-drawn</strong>
            </span>
            <span>
              Axis <strong>{meta.axis.name.replaceAll("_", " ")}</strong>
            </span>
            <span>
              Generated <strong>{meta.generated_at_utc}</strong>
            </span>
          </div>
        </div>
      </header>

      <main className="main">
        <TargetStrip members={delegation} />
        <Dashboard
          scores={scores}
          deviations={deviations}
          meta={meta}
          delegation={delegation}
        />
        <footer className="site-foot">
          Signed score = 2·(share of contested votes advancing the axis) − 1, over
          scoring-representative passage and amendment votes with an adjudicated valence. Bands are
          95% Wilson intervals. Procedural, nomination, cloture, and un-adjudicated votes are
          excluded. Party median lines on the forest plot are descriptive guides, not the weighted
          baseline used for defection detection. Sources: House Clerk EVS · Senate LIS.
        </footer>
      </main>
    </div>
  );
}
