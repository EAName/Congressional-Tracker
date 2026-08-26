# Seat model specification — `seat-v1.0`

Frozen 2026-08-19. This file is the pre-registration. Changing the functional
form, features, holdout rule, blend, or decision thresholds requires bumping
`model_version` in `config/seat_model.yaml` and adding a changelog row below.

## Estimand

For each tracked House race, publish:

- `prob_dem`: P(Democratic two-party win)
- 80% interval on Democratic two-party vote share
- a component decomposition of that share
- `blend`: `fundamentals_only` or `fundamentals_plus_polls`

`prob_rep` is `1 - prob_dem`. Third-party vote is out of scope.

## Data

Training extract: `data/seat_model/house_races_train.csv`, built from MIT
Election Data and Science Lab U.S. House 1976–2022 (TidyTuesday mirror of
Harvard Dataverse `doi:10.7910/DVN/IG0UN2`). Grain is one two-party
general-election race (specials dropped, `mode=TOTAL`).

Lean in training is **not** presidential PVI. It is the district's two-party
Democratic House share at the previous presidential election, minus that
year's national House two-party Democratic share. Production lean is
presidential two-party share from `data/races.json` minus the matching
national presidential two-party share. Transfer assumes House relative lean
and presidential relative lean are interchangeable at the coefficient. That
assumption is load-bearing and is why `lean_status` is published on every
race. If `races.json` lean shares are still null, lean is zeroed and labeled
`missing_zeroed`.

Incumbency (**changed in v1.1**): the previous cycle's **plurality winner**
across *all* general-election races, not just races with a two-party pairing.
v1.0 built this index from the two-party frame, which silently dropped
California/Washington top-two finals with no major-party opponent and New York
fusion races where only a minor party opposed. Those drops broke the incumbency
chain for the safest, longest-serving members, who then entered training as open
seats: v1.0 coded **27.8%** of races open against a real-world rate near 10%.
v1.1 codes 18.9%. Fusion rows are summed per candidate before the winner is
taken. Residual misses are still spelling variants across cycles.

Challenger quality (**changed in v1.1**): 1 if the Democratic non-incumbent won
a House seat at least two cycles back **and did not win in the immediately
preceding cycle**, -1 for the Republican analogue. v1.0 asked only "ever won,"
which tagged sitting safe-seat members whose incumbency detection had failed —
`qual_dem = 1` rows had a mean Democratic two-party share of 0.6985 against a
0.4942 baseline, and OLS priced the flag at +12.5 points. Under v1.1 those rows
mean 0.5702 against a 0.5016 baseline and the coefficient is +5.3 points. Production uses
`prior_federal_service` on the challenger in `races.json` (federal only;
statewide office is not encoded yet).

Fundraising: MEDSL has no receipts, so `log_ratio_dem` is identically 0 in
training and the OLS coefficient is unidentified. FEC receipts are attached
at prediction time for display (`components_raw`) but do not move `mu` until
a receipts-joined refit bumps the version.

Generic ballot: latest row in `data/generic_ballot.csv` with `date <= as_of`.
`nat_env = dem_two_party - 0.5`. Empty file → `nat_env = 0`, label
`neutral_default`. Do not scrape aggregators.

District polls: `data/district_polls.csv`. Recency weight
`exp(-ln(2) * age_days / 14) * n`. Precision-weighted blend with
fundamentals `N(μ_f, σ_f)`. Zero polls → fundamentals only.

## Functional form

```
μ_ols = β0 + β_lean·lean_rel_dem + β_inc·inc_dem + β_mid·midterm_dem
        + β_fund·log_ratio_dem + β_qual·qual_dem
μ = μ_ols + 1.0·nat_env
P(Dem win) = Φ((μ − 0.5) / σ)
80% share interval = μ ± z_0.90 · σ
```

`inc_dem` is +1 Democratic incumbent, −1 Republican incumbent, 0 open.
`midterm_dem` is −1 when the sitting president is a Democrat in a midterm,
+1 when Republican, 0 in presidential years.

`nat_env` is **not** estimated. Cycle-level national House share is collinear
with the midterm dummy, so the coefficient is frozen at 1.0 and added after
OLS: a +1pp generic-ballot Democratic two-party shift moves district `μ` by
+1pp. Empty generic ballot → `nat_env = 0`.

OLS `σ` is the residual RMSE on the training design. A logit MLE on the same
design is stored in the fit summary and is **not** the published probability.

## Train / holdout

Train years: 2010, 2014, 2016, 2018, 2020. 2012 and 2022 are excluded from
training because district numbers are not a panel across redistricting. 2024
is not in the committed MEDSL extract.

Holdout: FiveThirtyEight Deluxe toss-ups as of 2022-11-08 where neither party
had ≥60% win probability, minus AK-AL (RCV). Source URL is in
`config/seat_model.yaml`. Metric: Brier vs an always-incumbent baseline
(open seats dropped from that baseline).

## Tested and rejected

Measured by leave-one-cycle-out Brier over the five training cycles (n=1,946),
not by the 12-race 2022 holdout, which is too small to separate candidate
models. Baseline is `seat-v1.1` as shipped: **0.0702**.

### Per-district elasticity of the national environment

`nat_env` is applied uniformly — a +1pp generic-ballot move shifts every
district's μ by +1pp. The obvious objection is that real districts differ in how
hard they swing with the national environment. Three specifications were tried:

| specification | LOCO Brier | verdict |
|---|---|---|
| uniform swing (shipped) | 0.0702 | — |
| `nat_env × \|lean\|`, coefficient estimated | **0.0685** | **rejected** |
| `nat_env × exp(-k·\|lean\|)`, k grid-searched | 0.0691 at k=6 | rejected |

The linear form gives the best Brier of anything tested and is still wrong. Its
fitted coefficient is −5.697, so the effective environment multiplier
`1 + β·|lean|` crosses zero at `|lean| = 0.176` and inverts beyond it: **28% of
training rows, and 4 of 11 Virginia districts**, would respond to a pro-
Democratic national environment by moving toward Republicans. VA-8 (Beyer,
|lean| 0.262) gets a multiplier of −0.49. The Brier gain is free money from
seats already pinned near P=1, where a sign error costs nothing in the metric.

The constrained form cannot invert, but improves monotonically through k=6 with
no interior optimum — damping safe-seat response to 21%. That is not an
elasticity being identified; it is shrinkage arriving through the environment
term, because a damped `nat_env` leaves more variance for OLS to absorb.

### Heteroskedastic σ

Residual RMSE really is about 3× higher in the most marginal districts than in
the 0.15–0.25 lean band, and 82% of Brier loss sits in the three most marginal
bins against 2.8% in the safest. That suggests a σ that widens as `|lean| → 0`.
It does not work:

| σ model | LOCO Brier |
|---|---|
| constant (shipped) | **0.0702** |
| `σ·(1 + 0.5·exp(-\|lean\|/0.05))` | 0.0728 |
| `σ·(1 + 2.0·exp(-\|lean\|/0.05))` | 0.0801 |
| `σ·(1 + 0.5·min(1, \|lean\|/0.20))` — opposite direction | 0.0730 |

Monotonically worse in both directions; constant σ sits at a local optimum.
Brier does not reward matching residual variance, it rewards being decisive when
correct. Widening σ in marginal seats pulls P toward 0.5, and the model gets
more than half of those races right, so hedging costs more than the misses save.
The marginal bin carries high loss because those races are genuinely hard, not
because the model is miscalibrated about them.

### What would change this

A specification that constrains the multiplier to `(0, 1]` *and* has an interior
optimum, or an elasticity estimated from a source other than lean itself
(district-level swing history, which redistricting makes hard to panel). Absent
that, uniform swing is the defensible choice — not because it is obviously
right, but because the alternatives tested either invert the environment or fail
to converge.

## Decision rules

- Same-day re-append of `(race_id, date, model_version)` is a no-op.
- Mutating or deleting a historical predictions row fails CI.
- `prob_dem` must lie in `[0, 1]`.
- Published `model_version` must match `config/seat_model.yaml`.

## Changelog

| version | date | change | reason |
|---|---|---|---|
| seat-v1.0 | 2026-08-19 | Initial freeze | Prompt 13 pre-registration |
| seat-v1.1 | 2026-08-22 | Documented three rejected alternatives (per-district elasticity ×2, heteroskedastic σ) under **Tested and rejected**. No functional-form change, so no version bump. |
| seat-v1.1 | 2026-08-20 | Incumbency index rebuilt from all-race plurality winners; `qual_dem` requires a win two or more cycles back and no win in the preceding cycle | v1.0 coded 27.8% of training races as open seats (real rate ~10%) because top-two and fusion races were dropped from the winner index. `qual_dem` absorbed the resulting misclassified safe-seat incumbents at +12.5pp, which put a challenger at 80% win probability in a Trump+12 district. Holdout Brier moved 0.2196 → 0.2566, but the 12-race holdout is too small to adjudicate and the v1.0 figure was computed on the same contaminated features. |
