import type { Metadata } from "next";
import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import type { Meta, MethodologyDoc, PartyBaseline, WorkedExample } from "@/lib/types";
import { shortName, themeLabel } from "@/lib/types";
import { fmtScore } from "@/lib/viz";
import metaJson from "@/data/meta.json";
import methodologyJson from "@/data/methodology.json";

export const metadata: Metadata = {
  title: "Methodology · Congressional Vote Tracker",
  description:
    "Vote selection, signed-score formula, empirical Bayes hyperparameters, uncertainty, and reproduction commands.",
};

const doc = methodologyJson as MethodologyDoc;

const fmt = (v: number, d = 2) => v.toFixed(d);
const signed = (v: number) => fmtScore(v);

function district(ex: WorkedExample): string {
  if (ex.district_number != null) return `VA-${ex.district_number}`;
  return ex.chamber;
}

function baselineRows(rows: PartyBaseline[]) {
  return [...rows].sort(
    (a, b) => a.theme.localeCompare(b.theme) || a.party.localeCompare(b.party),
  );
}

export default function MethodologyPage() {
  const meta = metaJson as Meta;
  const s = doc.scoreable;
  const ex = doc.worked_example;
  const sepWeak = doc.separation.weakly_informative;
  const sepLive = doc.separation.worked_example_prior;

  return (
    <div className="shell method-shell">
      <SiteHeader
        active="methodology"
        daysUntilElection={meta.days_until_election}
        electionDate={meta.election_date}
      />
      <article className="method">
        <header className="method-head">
          <p className="method-kicker">Methods</p>
          <h1>How the scores are built</h1>
          <p className="method-lede">
            Written so a technically literate skeptic, including one who disagrees with the
            political project, can rerun the pipeline and match every published number. This site
            is sponsored by Democrats for Virginia. The estimator does not know that.
          </p>
        </header>

        <section id="reproduce">
          <h2>Reproduce this</h2>
          <p>
            Three commands from a clean machine. <code>data/votes.csv</code> is the adjudication
            input; <code>vact export-web</code> recomputes scores, empirical Bayes hyperparameters,
            and this page&apos;s worked example. No number on the scorecard is stored in the
            warehouse.<sup><a href="#fn-persist">1</a></sup>
          </p>
          <pre className="reproduce">
            <code>{doc.reproduce.join("\n")}</code>
          </pre>
        </section>

        <section id="selection">
          <h2>1. Vote selection</h2>
          <p>
            The measured axis is <strong>{s.axis_name.replaceAll("_", " ")}</strong>: {s.axis_description}{" "}
            Direction is not inferred from party. It is a per-vote valence: does a YEA advance
            that axis (+1) or oppose it (−1)?
          </p>
          <p>
            A roll call enters a score only if all of the following hold:
          </p>
          <ol>
            <li>
              <code>vote_category</code> is in {s.include_categories.join(", ")}. Currently
              excluded: {s.exclude_categories.join(", ")}.
            </li>
            <li>
              An adjudicated valence of ±1 exists for that <code>(vote_id, impact_tag)</code>.
              Un-adjudicated pairs (no valence row, or valence 0) are dropped. RULE-proposed
              valence is a proposal until a human promotes it.
            </li>
            {s.exclude_rule_resolutions ? (
              <li>
                Special-rule resolutions (“Providing for consideration of …”) are excluded even
                when they land in PASSAGE. They set debate terms; they are not a policy position
                on the underlying bill.
              </li>
            ) : null}
          </ol>
          <p>
            “Procedural” here means the excluded categories plus those special-rule resolutions.
            It is a category filter, not a judgment that the vote was unimportant.
          </p>
          <p>
            Adjudication lives in the public file{" "}
            <a href={doc.votes_url}>data/votes.csv</a> (unique key{" "}
            <code>member_bioguide_id, rollcall_id, theme</code>). Valence was exported from{" "}
            <code>fact_vote_valence</code>; the CSV is what scoring reads at runtime. Who
            adjudicated is the <code>adjudicator</code> column (HUMAN / RULE / LLM). Join key
            across the system is <code>bioguide_id</code> only.{" "}
            <a href="/corrections">Corrections policy</a>.
          </p>
        </section>

        <section id="scoring">
          <h2>2. Scoring</h2>
          <p>
            Let <em>n</em> be the member&apos;s contested votes (YEA or NAY) on a theme, and{" "}
            <em>k</em> the count that advanced the axis. Absences (NOT_VOTING, PRESENT) do not
            enter <em>k</em> or <em>n</em>; they are reported separately as an absence rate. A
            cell is labeled sufficient when <em>n</em> ≥ {s.min_contested}.
          </p>
          <p>
            Cosponsorship is a second signal, not a second vote. Among{" "}
            <a href={`${doc.repo_url}/blob/main/data/bills_candidates.csv`}>
              adjudicated bills
            </a>{" "}
            a member sponsored or cosponsored, <em>k</em>/<em>n</em> is the share that advance
            the axis, shrunk with the same beta-binomial estimator. Silence is not a Nay.
            Cosponsorship is cheap talk relative to a floor vote, so it is drawn as a hollow
            marker on the forest plot and is never averaged into the headline score.
          </p>
          <pre className="formula">
            <code>{`p_raw = k / n
raw_score = 2 p_raw − 1          ∈ [−1, +1]
Wilson band = 2 · Wilson(k, n; z=${s.wilson_z}) − 1`}</code>
          </pre>
          <p>
            Vote depths are small, so the published default is a beta-binomial empirical Bayes
            estimate, fit separately per (theme, party).<sup><a href="#fn-party">2</a></sup> Method:{" "}
            <code>{s.eb_method}</code>. Caucuses with fewer than {s.eb_min_caucus} members who
            cast a contested vote use Beta({s.eb_fallback_alpha}, {s.eb_fallback_beta}) and are
            flagged <code>weakly_informative</code>. Unanimous caucuses use a pooled prior with
            half-pseudocounts (<code>degenerate</code>) so the prior mean stays at the caucus
            edge instead of 0.5.
          </p>
          <pre className="formula">
            <code>{`prior      Beta(α, β)     from the caucus (k_i, n_i)
posterior  Beta(α + k, β + n − k)
eb_score   = 2 · (α+k) / (α+β+n) − 1
cred band  = 2 · Beta-quantile_{0.025, 0.975} − 1`}</code>
          </pre>

          <h3>Hyperparameters in this build</h3>
          <p>
            These α, β values are written at export time from the live frame. They will change
            when <code>data/votes.csv</code> changes.
          </p>
          <div className="method-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Theme</th>
                  <th>Party</th>
                  <th>α</th>
                  <th>β</th>
                  <th>Source</th>
                  <th>EB center</th>
                  <th>Members</th>
                </tr>
              </thead>
              <tbody>
                {baselineRows(doc.baselines).map((b) => (
                  <tr key={`${b.theme}-${b.party}`}>
                    <td>{themeLabel(b.theme)}</td>
                    <td>{b.party}</td>
                    <td>{fmt(b.prior_alpha, 3)}</td>
                    <td>{fmt(b.prior_beta, 3)}</td>
                    <td>
                      <code>{b.prior_source}</code>
                    </td>
                    <td>{signed(b.eb_center)}</td>
                    <td>{b.n_members}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {ex ? (
            <>
              <h3>Worked example</h3>
              <p>
                {shortName(ex.full_name)} ({ex.party}, {district(ex)}), theme{" "}
                {themeLabel(ex.theme)}. This cell had the largest |EB − raw| among sufficient
                cells in the current export.
              </p>
              <ol className="worked">
                <li>
                  Counts: k = {ex.k} advancing votes out of n = {ex.n} contested, so p_raw ={" "}
                  {ex.k}/{ex.n} = {fmt(ex.p_raw, 4)}.
                </li>
                <li>
                  Raw signed score: 2 × {fmt(ex.p_raw, 4)} − 1 = {signed(ex.raw_score)}. Wilson
                  95% band [{signed(ex.wilson_lo)}, {signed(ex.wilson_hi)}].
                </li>
                <li>
                  Caucus prior: Beta({fmt(ex.prior_alpha, 4)}, {fmt(ex.prior_beta, 4)}), source{" "}
                  <code>{ex.prior_source}</code>, mean {fmt(ex.prior_mean, 4)} (signed{" "}
                  {signed(2 * ex.prior_mean - 1)}).
                </li>
                <li>
                  Posterior: Beta({fmt(ex.post_alpha, 4)}, {fmt(ex.post_beta, 4)}) = Beta(
                  {fmt(ex.prior_alpha, 4)}+{ex.k}, {fmt(ex.prior_beta, 4)}+{ex.n - ex.k}). Mean{" "}
                  {fmt(ex.post_mean, 4)}.
                </li>
                <li>
                  Shrunk signed score: 2 × {fmt(ex.post_mean, 4)} − 1 = {signed(ex.eb_score)}.
                  Credible 95% band [{signed(ex.cred_lo)}, {signed(ex.cred_hi)}]. Shrinkage{" "}
                  {signed(ex.shrinkage)} from the raw point.
                </li>
              </ol>
            </>
          ) : (
            <p>No sufficient cell was available to use as a worked example in this export.</p>
          )}
        </section>

        <section id="uncertainty">
          <h2>3. Uncertainty</h2>
          <p>
            The 95% credible interval is the central 95% of the member&apos;s posterior Beta on
            the signed scale, given the fitted (theme, party) prior and that member&apos;s{" "}
            <em>k</em>, <em>n</em>. It is not a frequentist confidence interval, and it is not a
            statement about sampling from a superpopulation of bills. If the prior is wrong, the
            interval is wrong in the same direction.<sup><a href="#fn-cred">3</a></sup>
          </p>
          <p>
            Interval overlap on the compare module is a visual heuristic. Non-overlap is not a
            hypothesis test, does not control Type I error, and is not adjusted for the number of
            pairwise looks on the page.
          </p>
          <p>
            How much vote depth is needed to reliably separate two members 0.25 apart on the
            signed scale? Simulation, not a slogan: two independent binomials with true signed
            scores {signed(sepWeak.signed_true[0])} and {signed(sepWeak.signed_true[1])} (p ={" "}
            {sepWeak.p_true[0]} and {fmt(sepWeak.p_true[1], 4)}), equal <em>n</em>, 95% credible
            intervals, {sepWeak.n_sims} draws per <em>n</em>, 80% power defined as P(intervals
            disjoint).
          </p>
          <ul>
            <li>
              Under the weakly-informative fallback Beta({sepWeak.prior_alpha},{" "}
              {sepWeak.prior_beta}):{" "}
              {sepWeak.reached
                ? `n = ${sepWeak.n_needed} contested votes per member (achieved power ${sepWeak.power_at_n} at that n).`
                : `no n ≤ ${sepWeak.max_n} reached 80% power (power at n=${sepWeak.max_n} was ${sepWeak.power_at_max_n ?? "—"}; shrinkage toward a shared prior makes a 0.25 gap harder to declare than a Wilson calculation suggests).`}
            </li>
            {sepLive ? (
              <li>
                Under this build&apos;s worked-example prior Beta({fmt(sepLive.prior_alpha, 3)},{" "}
                {fmt(sepLive.prior_beta, 3)}), <code>{sepLive.prior_source}</code>:{" "}
                {sepLive.reached
                  ? `n = ${sepLive.n_needed} (${sepLive.power_at_n} power).`
                  : `no n ≤ ${sepLive.max_n} reached 80% power (power at n=${sepLive.max_n} was ${sepLive.power_at_max_n ?? "—"}).`}{" "}
                A peaked caucus prior can demand more votes to declare a 0.25 gap, because both
                members are pulled toward the same center.
              </li>
            ) : null}
          </ul>
          <p>
            Most published cells in this tracker have n in the single digits. A 0.25 gap is
            generally not identifiable at current depth. That is why the bands are the claim, not
            the point.
          </p>
        </section>

        <section id="falsification">
          <h2>4. Symmetry audit and falsification</h2>
          <p>
            Downstream scoring is party-blind arithmetic. Bias can enter when roll calls are
            chosen or when axis direction is coded. This build pre-registers inclusion in{" "}
            {doc.inclusion_spec_url ? (
              <a href={doc.inclusion_spec_url}>VOTE_INCLUSION_SPEC.md</a>
            ) : (
              <code>VOTE_INCLUSION_SPEC.md</code>
            )}{" "}
            and publishes every excluded pair in{" "}
            {doc.votes_excluded_url ? (
              <a href={doc.votes_excluded_url}>data/votes_excluded.csv</a>
            ) : (
              <code>data/votes_excluded.csv</code>
            )}
            .
          </p>
          {doc.symmetry_audit ? (
            <>
              <p>
                Spec version <code>{doc.symmetry_audit.inclusion_spec_version ?? "—"}</code>.
                Blind-coded share:{" "}
                {doc.symmetry_audit.coded_blind?.false_share_pp != null
                  ? `${doc.symmetry_audit.coded_blind.false_share_pp}% of roll-call × theme units not blind-coded`
                  : "—"}
                . Any tripped threshold is a signal to re-open adjudication, not proof of bias.
              </p>
              {doc.symmetry_audit.excluded_counts_by_reason &&
              Object.keys(doc.symmetry_audit.excluded_counts_by_reason).length > 0 ? (
                <>
                  <h3>Excluded roll calls by reason</h3>
                  <div className="method-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Reason</th>
                          <th>Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(doc.symmetry_audit.excluded_counts_by_reason)
                          .sort(([a], [b]) => a.localeCompare(b))
                          .map(([reason, count]) => (
                            <tr key={reason}>
                              <td>
                                <code>{reason}</code>
                              </td>
                              <td>{count}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
              {doc.symmetry_audit.caucus_advancing_by_theme &&
              doc.symmetry_audit.caucus_advancing_by_theme.length > 0 ? (
                <>
                  <h3>Caucus majority advancing the coded axis</h3>
                  <div className="method-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Theme</th>
                          <th>Dem share</th>
                          <th>Rep share</th>
                          <th>Gap (pp)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {doc.symmetry_audit.caucus_advancing_by_theme.map((row) => (
                          <tr key={row.theme}>
                            <td>{themeLabel(row.theme)}</td>
                            <td>
                              {row.dem_caucus_advancing_share != null
                                ? `${(100 * row.dem_caucus_advancing_share).toFixed(0)}%`
                                : "—"}
                            </td>
                            <td>
                              {row.rep_caucus_advancing_share != null
                                ? `${(100 * row.rep_caucus_advancing_share).toFixed(0)}%`
                                : "—"}
                            </td>
                            <td>{row.gap_pp ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
              {doc.symmetry_audit.flags ? (
                <>
                  <h3>Falsification thresholds</h3>
                  <ul>
                    {Object.entries(doc.symmetry_audit.falsification ?? {}).map(
                      ([key, meta]) => {
                        const threshold = doc.symmetry_audit?.thresholds?.[key];
                        const tripped = doc.symmetry_audit?.flags?.[key];
                        return (
                          <li key={key}>
                            <code>{key}</code>
                            {threshold != null ? ` (threshold ${threshold})` : ""}:{" "}
                            {meta.trip}
                            {tripped ? " — tripped in this build." : " — ok."}{" "}
                            {meta.action}
                          </li>
                        );
                      },
                    )}
                  </ul>
                </>
              ) : null}
            </>
          ) : (
            <p>Run <code>vact export-web</code> to populate live audit tables.</p>
          )}
        </section>

        <section id="limits">
          <h2>5. Known limitations</h2>
          <ul>
            <li>
              <strong>Small n.</strong> Sufficiency is n ≥ {s.min_contested}. Several themes still
              sit on the weakly-informative or degenerate prior because the caucus sample is thin
              or unanimous.
            </li>
            <li>
              <strong>Theme coverage.</strong> Only impact tags with adjudicated valence appear.
              A member can look extreme on a theme that has two votes and ordinary on one that
              has twelve.
            </li>
            <li>
              <strong>No consequence weights.</strong> A minibus and a narrow amendment count the
              same. Bill importance is not in the likelihood.
            </li>
            <li>
              <strong>Single-state scope.</strong> The scorecard is the Virginia delegation.
              Senate roll calls include 100 members in the warehouse; scoring still joins VA
              legislators only.
            </li>
            <li>
              <strong>Sponsorship.</strong> Democrats for Virginia pays for and publishes this
              site. Valence is a political judgment. The math above is the estimator, not a claim
              of neutrality about which bills belong on the axis.
            </li>
            <li>
              <strong>Map version.</strong> District attributes are keyed to map version 2021
              unless an export says otherwise. Mixing 2021 voting geography with 2026 targeting
              attributes votes to the wrong electorate.
            </li>
          </ul>
        </section>

        <section id="changelog">
          <h2>6. Changelog</h2>
          <p>
            Auto-generated from <code>git log</code> of <code>data/votes.csv</code>,{" "}
            <code>src/vact/analysis/scoring.py</code>, <code>src/vact/analysis/estimators.py</code>
            , and <code>config/scoring.yaml</code>.
          </p>
          {doc.changelog.length === 0 ? (
            <p>No git history was available at export time.</p>
          ) : (
            <div className="method-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Commit</th>
                    <th>Subject</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.changelog.map((c) => (
                    <tr key={c.sha}>
                      <td>{c.date}</td>
                      <td>
                        <a href={`${doc.repo_url}/commit/${c.sha}`}>
                          <code>{c.sha}</code>
                        </a>
                      </td>
                      <td>{c.subject}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section id="notes" className="footnotes">
          <h2>Notes</h2>
          <ol>
            <li id="fn-persist">
              Signed scores are never written to DuckDB. Only valence (the political input) is
              persisted. See AGENTS.md §8.
            </li>
            <li id="fn-party">
              A single national prior would shrink Democrats toward Republicans. The (theme,
              party) cell is the grouping on purpose.
            </li>
            <li id="fn-cred">
              Equal-tailed posterior quantiles, mapped through 2x−1. They are not highest-density
              intervals, and they inherit whatever misfit the method-of-moments (or MLE) prior
              has.
            </li>
          </ol>
        </section>
      </article>
      <SiteFooter />
    </div>
  );
}
