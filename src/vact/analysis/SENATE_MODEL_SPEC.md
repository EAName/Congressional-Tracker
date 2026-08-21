# Senate model specification — `senate-v0.1`

Frozen 2026-08-20. This file is the pre-registration. Changing the functional
form, features, validation scheme, blend, or decision thresholds requires
bumping `model_version` in `config/senate_model.yaml` and adding a changelog row
below.

## Estimand

For each tracked Senate race, publish:

- `prob_dem`: P(Democratic two-party win)
- 80% interval on Democratic two-party vote share
- a component decomposition of that share
- `blend`: `fundamentals_only` or `fundamentals_plus_polls`

`prob_rep` is `1 - prob_dem`. Third-party vote is out of scope.

## Why this is a separate model from `seat-v1.1`

The House model is fit on district-level features and cannot score a statewide
race: there is no district lean to feed it. Running it on a Senate contest would
produce a confident number with no basis. `va-sen` is therefore excluded from
`seat-v1.1` (`seats.json.unmodeled_races`) and scored here instead.

## Data

Training extract: `data/seat_model/senate_races_train.csv`, built by
`vact senate build-train` from:

- **MEDSL U.S. Senate statewide 1976–2024** (Harvard Dataverse
  `doi:10.7910/DVN/PEJ5QU`, file 13887039). Grain is one two-party regular
  general election per state-year; specials are excluded from the estimand.
- **State presidential two-party share**, parsed from the Wikipedia
  results-by-state tables for 2008/2012/2016/2020/2024 into
  `data/raw/wikipedia/president_state_two_party.csv`. The MEDSL presidential
  files are gated behind a Dataverse guestbook and are not fetched
  automatically; a maintainer who accepts those terms can substitute them.

Two structural advantages over the House model, both worth stating plainly:

1. **Every cycle is usable.** `seat-v1.1` drops 2012 and 2022 because district
   numbers are not a panel across redistricting. States are a permanent panel,
   so training spans all eight cycles 2010–2024 (244 races).
2. **No lean transfer.** `seat-v1.1` trains on lagged *House* share and predicts
   from *presidential* share, an assumption SEAT_MODEL_SPEC.md flags as
   load-bearing. Here `lean_rel_dem` is state presidential two-party Democratic
   share minus the national presidential two-party Democratic share of the same
   election, in both training and production. There is no transfer to assume.

**Incumbency**: `inc_dem` is +1 / -1 / 0 for a Democratic / Republican / no
sitting senator in the race. A candidate counts as sitting if their normalized
name won any Senate general in that state in the previous six years — regular or
special, and including races with no two-party pairing. Keying strictly on
year-6 misses senators appointed to a vacancy and then confirmed in a special,
and states whose classes fall out of the regular rhythm. The extract codes 32.8%
of races open. Residual misses are cross-cycle spelling variants and appointed
senators who have never won an election.

**National environment**: `nat_env` is the national two-party Democratic share of
the **U.S. House** vote for that cycle, centred at 0.5 — the quantity the generic
ballot forecasts, so training and production use the same construct. Computed
from the MEDSL House extract through 2022; 2024 comes from a cited constant in
`senate_train.NATIONAL_HOUSE_OVERRIDE` because the committed House extract stops
at 2022.

**Polls**: `data/district_polls.csv`, filtered to `race_id`. Recency weight
`exp(-ln(2) * age_days / 14)`, precision-weighted against the fundamentals.
Zero polls → `fundamentals_only`.

**Not included, on purpose**: candidate quality, fundraising, and a midterm
dummy. At n=244 with cycle-correlated errors, the effective sample will not
support them, and `seat-v1.0`'s `qual_dem` is a live demonstration of what a
weakly-identified feature does to published numbers. `midterm_dem` was tested
and dropped: leave-one-cycle-out Brier was **identical** at 0.0885 with and
without it, because `nat_env` already carries the cycle environment and the
dummy is constant within a cycle.

## Functional form

```
μ = β0 + β_lean·lean_rel_dem + β_inc·inc_dem + 1.0·nat_env
P(Dem win) = Φ((μ − 0.5) / σ)
80% share interval = μ ± z_0.90 · σ
```

`nat_env` is **not** estimated. It is constant within a cycle, so its
coefficient is not separately identifiable; it is frozen at 1.0 and added after
OLS. A +1pp generic-ballot Democratic shift moves `μ` by +1pp.

σ is the residual RMSE on the training design.

## Validation

**Leave-one-cycle-out**, not a single holdout. Each of the eight cycles is held
out in turn, the model refit on the other seven, and the held-out cycle scored.
A single 33-race holdout cannot separate candidate models at this sample size;
this is the concrete lesson from `seat-v1.1`, whose 12-race holdout Brier moved
0.2196 → 0.2566 on a change that demonstrably fixed the training data.

Two baselines, both of which the model must beat to ship:

| Model | LOCO Brier (n=244) |
|---|---|
| `senate-v0.1` | **0.0885** |
| lean + uniform swing (no incumbency) | 0.1232 |
| always-incumbent (0.5 for open seats) | 0.1516 |

## Fitted coefficients

| feature | β |
|---|---|
| intercept | +0.4941 |
| lean_rel_dem | +0.5321 |
| inc_dem | +0.0615 |
| nat_env | 1.0 (frozen) |
| σ | 0.0734 |

Senate incumbency at 6.2pp sits below the 7.2pp `seat-v1.1` estimates for the
House, which is the expected direction.

## Decision rules

- `prob_dem` must lie in `[0, 1]`.
- Published `model_version` must match `config/senate_model.yaml`.
- A race with `lean_status = missing_zeroed` must not be published as a forecast.
- Any successor model must beat `senate-v0.1` on leave-one-cycle-out Brier
  before it replaces it.

## Changelog

| version | date | change | reason |
|---|---|---|---|
| senate-v0.1 | 2026-08-20 | Initial freeze | State presidential lean + incumbency + frozen uniform swing + poll blend, fit on 244 races over eight cycles |
