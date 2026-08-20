import Dashboard from "@/components/Dashboard";
import SiteHeader from "@/components/SiteHeader";
import TargetStrip from "@/components/TargetStrip";
import type { CosponsorshipDoc, Deviation, IrtDoc, Member, Meta, Score, TimeSeriesDoc } from "@/lib/types";
import cosponsorshipJson from "@/data/cosponsorship.json";
import delegationJson from "@/data/delegation.json";
import deviationsJson from "@/data/deviations.json";
import irtJson from "@/data/irt.json";
import metaJson from "@/data/meta.json";
import scoresJson from "@/data/scores.json";
import timeseriesJson from "@/data/timeseries.json";

export default function Page() {
  const scores = scoresJson as Score[];
  const deviations = deviationsJson as Deviation[];
  const meta = metaJson as Meta;
  const delegation = delegationJson as Member[];
  const timeseries = timeseriesJson as TimeSeriesDoc;
  const irt = irtJson as IrtDoc;
  const cosponsorship = cosponsorshipJson as CosponsorshipDoc;

  return (
    <div className="shell">
      <SiteHeader
        active="scorecard"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />

      <div className="workspace">
        <TargetStrip members={delegation} />
        <Dashboard
          scores={scores}
          deviations={deviations}
          meta={meta}
          delegation={delegation}
          timeseries={timeseries}
          irt={irt}
          cosponsorship={cosponsorship}
        />
        <footer className="site-foot">
          Signed score = 2·(share of contested votes advancing the axis) − 1. Default display is
          an empirical Bayes shrinkage of that share toward the member's (theme, party) caucus,
          with 95% credible intervals; toggle Raw for Wilson bands on the unshrunk estimate.
          Compare reports whether intervals overlap under current vote depth — separation is
          suggestive, not a formal hypothesis test. Procedural and un-adjudicated votes excluded.
          Sources: House Clerk EVS · Senate LIS.{" "}
          <a href="/methodology">Full methodology</a>.
        </footer>
      </div>
    </div>
  );
}
