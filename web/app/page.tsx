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
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand-block">
            <p className="product">Congressional Vote Tracker</p>
            <h1 className="brand">Democrats for Virginia</h1>
          </div>
        </div>
      </header>

      <div className="workspace">
        <TargetStrip members={delegation} />
        <Dashboard
          scores={scores}
          deviations={deviations}
          meta={meta}
          delegation={delegation}
        />
        <footer className="site-foot">
          Signed score = 2·(share of contested votes advancing the axis) − 1. Default display is
          an empirical Bayes shrinkage of that share toward the member's (theme, party) caucus,
          with 95% credible intervals; toggle Raw for Wilson bands on the unshrunk estimate.
          Compare reports whether intervals overlap under current vote depth — separation is
          suggestive, not a formal hypothesis test. Procedural and un-adjudicated votes excluded.
          Sources: House Clerk EVS · Senate LIS.
        </footer>
      </div>
    </div>
  );
}
