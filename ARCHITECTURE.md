# Architecture — current vs target (FiveThirtyEight-grade analytics)

Audit date: 2026-08-19. No behavior change in this commit.

This document is the Prompt 0 deliverable. Prompt 1 (`data/votes.csv`) is
implemented: warehouse export, validation, CSV-backed scoring, DuckDB SQL path
behind `--from-warehouse`.

---

## 1. Current architecture

### 1.1 What this repo actually is

Two layers, one git repo:

| Layer | Path | Runtime |
|---|---|---|
| Ingest / warehouse / analysis | `src/vact/` | Python 3.11, DuckDB, Typer `./bin/vact` |
| Presentation | `web/` | Next.js 15, static JSON, Vercel (`Root Directory = web`) |

Google Sheets is an **audit export**, not a backend. `vact sheets push` writes
live warehouse queries into a workbook
([`1fbjfNKB79-Rzq70X9Ixg67aVzxYmv6nxxj-hCVQDyi0`](https://docs.google.com/spreadsheets/d/1fbjfNKB79-Rzq70X9Ixg67aVzxYmv6nxxj-hCVQDyi0)).
The Vercel app never calls Sheets. It never calls DuckDB. It imports
`web/data/*.json` at **build time**.

Failure mode if Prompt 1 treats Sheets as canonical: the Vote Detail tab is a
lossy, publication-gated projection. Valence lives in `fact_vote_valence`, not
in the sheet. A Sheets→CSV sync would drop axis direction unless we first
write valence onto the sheet (we do not today).

### 1.2 Data entry (network → warehouse)

```
clerk.house.gov EVS XML
senate.gov LIS XML
unitedstates/congress-legislators YAML
congress.gov bills (optional; CONGRESS_API_KEY)
        │  src/vact/http_client.py  (shared UA + tenacity)
        ▼
data/raw/{source}/{yyyy}/{id}.{ext}     immutable landing; parse never hits network
        │  sources/*.py fetch() / parse() stay separate
        ▼
data/warehouse/warehouse.duckdb         gitignored
```

Grain that matters for scoring:

- `fact_vote` — one roll call. `vote_category` from `ref_vote_category_rule`.
- `fact_member_vote` — `(vote_id, bioguide_id, position)` YEA/NAY/PRESENT/NOT_VOTING.
- `bridge_vote_impact` — `(vote_id, impact_tag)` RULE/HUMAN/LLM. Theme assignment.
- `fact_vote_valence` — `(vote_id, impact_tag, valence ∈ {-1,0,1}, valence_source)`.
  Political judgment. The **only** persisted scoring input (AGENTS.md §8).
- `dim_legislator` — VA SCD2. Join key is `bioguide_id` only.
- `dim_district` — lean / `is_target` keyed by `map_version` (`2021` operative).
- `dim_bill.plain_language_summary` — activist publication gate (not used by `web/`).

CLI path: `vact incremental` → `vact classify` → `vact valence propose|set` →
`vact score` / `vact deviations` / `vact export-web`.

### 1.3 Signed score formula (canonical)

Implemented once in Python:

```
p      = n_pro / n_contested
score  = 2p − 1                         ∈ [-1, +1]
band   = 2 · Wilson(p; z=1.96) − 1
```

`n_pro` = contested votes where the member advanced the axis:

```
(position = YEA  AND valence = +1)
OR (position = NAY  AND valence = −1)
```

`n_contested` = YEA + NAY only. NOT_VOTING / PRESENT → `absence_rate`, never Nay.

Scoreable filter (`config/scoring.yaml`):

- `vote_category ∈ {PASSAGE, AMENDMENT}`
- valence `±1` on that `(vote, tag)`
- special-rule resolutions (`hres`/`sres` “Providing for consideration…”) excluded
- procedural / cloture / nomination / suspension / MTR never enter

`sufficient` iff `n_contested ≥ 3`.

Wilson is the Wilson score interval on the binomial proportion, mapped through
the same affine transform. Degenerate `n=0` → proportion band `[0,1]` and
`signed_score = None`.

**These numbers are never stored in DuckDB.** `build_scores_frame()` recomputes
them on every call.

### 1.4 Within-party deviations

`compute_party_deviations()` in `src/vact/analysis/deviations.py`:

1. Party baseline = **weighted median** of sufficient members’ signed scores,
   weights = `n_contested`.
2. `deviation = score − baseline`.
3. `defection_votes` = roll calls where `sign(direction × valence)` opposes the
   party-majority direction on that same vote. Absences cannot be defections.

### 1.5 How each frontend module consumes data

Vercel build: Next.js statically imports JSON. No fetch, no API routes.

| Artifact | Producer | Consumer modules |
|---|---|---|
| `web/data/scores.json` | `vact export-web` ← `build_scores_frame` | Forest plot, party spread, delegation strip, compare, evidence bars, target profiles |
| `web/data/deviations.json` | same ← `compute_party_deviations` | Defection panel; gold “crossed caucus” flags |
| `web/data/delegation.json` | same ← `list_delegation` | Target strip, delegation strip, target profiles, default compare pins |
| `web/data/meta.json` | same | theme list, `sufficient_min`, party baselines |
| `web/data/methodology.json` | same ← `build_methodology_payload` | `/methodology` |
| `web/data/timeseries.json` | same ← `expanding_series` | Score over time, biggest-mover card |
| `web/data/cosponsorship.json` | same ← `score_cosponsorship` | Forest hollow marker (never blended) |

Module → fields:

- **Forest plot** (`ForestPlot.tsx`): plots `signed_score` + `[wilson_low, wilson_high]`.
  Dashed party lines come from an **unweighted** median recomputed in
  `Dashboard.tsx` (not the Python weighted median). Click/hover links `bioguide_id`.
- **Party spread** (`PartySpread.tsx`): beeswarm of `signed_score` by party.
- **Delegation strip** (`DelegationStrip.tsx`): district-order dots from scores
  joined to delegation; missing cell = insufficient.
- **Compare** (`CompareOverlay.tsx`): two members’ Wilson intervals on one axis;
  delta and overlap are **interval comparisons of precomputed bounds**, not a
  new estimator.
- **Defections** (`Dashboard.tsx`): rows from `deviations.json`; expand shows
  `defection_votes[]` with clerk/LIS `source_link`.
- **Target profiles** (`TargetProfiles.tsx`): member score vs **another**
  unweighted party median, per theme.
- **Evidence bars** (`EvidenceBars.tsx`): `sum(n_contested)` per theme. Display
  aggregation only.

`n_pro` / `k` is **not** in `scores.json` today. Prompt 2 (EB) needs `k` and `n`
per cell; that is a schema add on the derived artifact, not a frontend formula.

### 1.6 Other surfaces (not Vercel)

- **Sheets** (`src/vact/exports/sheets.py`): Dashboard Yea/Nay scorecards
  (`exports/data.py` counts Y/N on tagged votes, **no valence / no signed
  score**), plus Signed Scores / Party Deviations tabs that *do* call
  `build_scores_frame`.
- **`docs/`** (`vact site`): publication-gated activist HTML (GitHub Pages-era).
  Still what `.github/workflows/publish.yml` builds. Does **not** run
  `export-web`. Vercel prod can therefore lag the warehouse until someone
  commits `web/data/*.json`.

---

## 2. Scoring logic: every file that contains it

### 2.1 Canonical math (source of truth)

| File | What |
|---|---|
| `src/vact/analysis/scoring.py` | `wilson_interval`, `signed_score_from_counts` (`2p−1`), `n_pro` SQL, `build_scores_frame`, `sufficient` |
| `config/scoring.yaml` | axis, scoreable categories, `wilson.z`, `sufficiency.min_contested`, deviation thresholds |
| `src/vact/analysis/deviations.py` | `weighted_median`, `_aligned` (`direction × valence`), party-majority defection test |
| `tests/test_scoring.py` | Wilson / signed-score unit tests + frame fixtures |
| `tests/test_deviations.py` | synthetic caucus defection fixtures |

### 2.2 Serialization / CLI (no new formula)

| File | What |
|---|---|
| `src/vact/exports/web.py` | copies frame fields into JSON (drops `n_pro`, `n_not_voting`, `n_present`) |
| `src/vact/exports/sheets.py` | `build_signed_scores_matrix`, `build_party_deviations_matrix` |
| `src/vact/cli.py` | `vact score`, `vact deviations`, `vact valence *`, `vact export-web` |
| `sql/schema.sql` | `fact_vote_valence` (input, not a metric) |

### 2.3 Parallel product math (different estimator)

| File | What | Relation to signed score |
|---|---|---|
| `src/vact/exports/data.py` | Yea/Nay tallies `"{yea}Y / {nay}N"` on tagged votes, excluding only NOMINATION/CLOTURE | **Not** axis-signed. Used by Sheets Dashboard + `docs/` site |

### 2.4 Frontend recomputation (duplication / drift)

| File | What | Drift vs Python |
|---|---|---|
| `web/components/Dashboard.tsx` `median()` | unweighted median of sufficient signed scores → forest dashed lines | Python defection baseline is **weighted** median by `n_contested` |
| `web/components/TargetProfiles.tsx` `median()` | same unweighted median vs caucus tick | duplicate of Dashboard, still unweighted |
| `web/components/CompareOverlay.tsx` | `delta = scoreA − scoreB`; overlap iff Wilson bands intersect | comparison of exported bounds; OK if estimators stay in JSON |
| `web/components/EvidenceBars.tsx` | `sum(n_contested)` | aggregation, not a score |
| `web/lib/viz.ts` | `fmtScore` only | display |

Chart components (`ForestPlot`, `PartySpread`, `DelegationStrip`) **plot
precomputed numbers**. They do not implement `2p−1` or Wilson.

### 2.5 Not scoring

Classify (`transforms/classify.py`, `config/impact_rules.yaml`), vote_category
rules, publication gate (`exports/publication.py`), district targets
(`config/districts.yaml`). These decide *which rows exist*, not the estimator.

---

## 3. Duplication summary (the swap problem)

Today you cannot replace Wilson with empirical Bayes without touching:

1. `scoring.py` (correct place).
2. `exports/web.py` + `web/lib/types.ts` (schema: add `eb_*`, keep `raw_*`).
3. Every chart that binds `signed_score` / `wilson_*` by name
   (`ForestPlot`, `CompareOverlay`, `PartySpread`, `DelegationStrip`,
   `TargetProfiles`, tooltips).
4. Frontend `median()` dashed lines, which will disagree with EB caucus
   posteriors unless baselines are exported too.

That is the coupling Prompt 2–4 must break.

---

## 4. Target architecture

Principle: **estimators live in Python. Charts bind a named estimate + interval
from JSON.** Swapping raw → EB → IRT is a field rename / toggle against the
same geometry, not a new formula in TSX.

```
Upstream APIs
    │
    ▼
data/raw/  +  DuckDB warehouse          ingest / classify / valence (unchanged)
    │
    ▼
data/votes.csv                          versioned adjudication grain
    │                                   one row per (bioguide_id, rollcall_id, theme)
    │                                   git log = audit trail
    ▼
src/vact/analysis/estimators.py         raw Wilson | beta-binomial EB | (later) read IRT JSON
src/vact/analysis/deviations.py         defections; consume estimator output, do not re-score
    │
    ▼
data/derived/*.json                     scores, deviations, delegation, meta,
                                        timeseries, irt, forecasts (build artifacts)
    │
    ▼
web/                                    presentation only
    import derived JSON at build
    estimate_id: "raw" | "eb" | "irt"
    interval: { lo, hi, kind: "wilson" | "credible" | "hdi" }
```

### 4.1 Canonical adjudication file (`data/votes.csv`)

Prompt 1’s schema, mapped from **warehouse**, not from Sheets:

| CSV column | Warehouse source |
|---|---|
| `member_bioguide_id` | `fact_member_vote.bioguide_id` |
| `member_name`, `district`, `party` | `dim_legislator` + `map_version=2021` |
| `congress`, `chamber`, `rollcall_id`, `rollcall_date`, `bill_id` | `fact_vote` |
| `theme` | `bridge_vote_impact.impact_tag` / valence tag |
| `axis_direction` | `fact_vote_valence.valence` → `advance` (`+1`) / `oppose` (`-1`) |
| `vote_cast` | `fact_member_vote.position` |
| `contested` | YEA/NAY |
| `adjudicator`, `adjudication_date` | `valence_source`, `adjudicated_at_utc` |
| `source_url` | `fact_vote.source_url` |
| `adjudication_note` | new (empty until humans fill) |

Sheets sync is a **reconciliation diff** against Vote Detail / Signed Scores,
not the writer of `axis_direction`.

All downstream scoring reads this file (or a DuckDB view of it). Runtime Sheets
fetch is forbidden.

### 4.2 Estimator module contract

Single function family, e.g.:

```python
def estimate_member_theme(rows: list[VoteRow], spec: EstimatorSpec) -> Estimate:
    # Estimate: { raw_score, wilson_lo, wilson_hi,
    #             eb_score, cred_lo, cred_hi, n, k,
    #             prior_alpha, prior_beta, prior_source }
```

IRT is a separate offline pipeline (`analysis/irt_pipeline.py`) emitting
`data/derived/irt.json`. Frontend “Ideal points” module reads that file. MCMC
never runs on Vercel.

Charts accept:

```ts
type Interval = { lo: number; hi: number; kind: "wilson" | "credible" | "hdi" };
type PointEstimate = { value: number; n: number; k: number; interval: Interval };
```

Forest / compare default to `eb` once Prompt 2 lands; toggle shows `raw`.

### 4.3 Build / deploy

| Step | Owner |
|---|---|
| Ingest + classify + valence | existing GitHub Actions (Ingest / Dimensions) |
| Emit `data/votes.csv` + validation | new `vact votes export` + CI check |
| Emit `data/derived/*.json` | `vact export-web` (or `make derived`) |
| Commit derived JSON **or** generate in CI before Vercel | Publish workflow must call `export-web` (today it only `make site`) |
| Vercel | Next.js static from `web/`; Root Directory `web`; **no Python on Vercel** |

Do not put DuckDB or PyMC on the Vercel build. Vercel remains a static host.

### 4.4 What we explicitly will not do

- Blend cosponsorship into the headline score (Prompt 6: secondary hollow marker).
- Persist signed scores in DuckDB (AGENTS.md §8 still holds; derived JSON is a
  build artifact, like `docs/`, not a warehouse metric).
- Auto-publish editorial notes (Prompt 8: draft + human commit).

---

## 5. Migration checklist

Prompt 0 (this file) — **done**. No behavior change.

**Prompt 1 — versioned vote layer**

- [x] Define `data/votes.csv` schema + Pydantic model
- [x] `vact votes export` from warehouse (map_version=2021, scoreable filter)
- [x] Diff report vs previous committed CSV
- [x] Validation: unique `(member, rollcall, theme)`, axis_direction + source_url
      required, party consistent per member, vote_cast enum
- [x] Point `build_scores_frame` (or a new reader) at the CSV; keep DuckDB path
      behind `--from-warehouse` until / after byte-identical
- [x] Prove byte-identical `signed_score` / Wilson vs warehouse SQL (and vs
      `web/data/scores.json` once both are committed)
- [x] Optional: Sheets reconciliation (read-only diff), not Sheets-as-source
      (`vact votes sync --sheets`)
- [x] Wire validation into CI; document `git log data/votes.csv` as audit trail

**Prompt 2 — empirical Bayes**

- [x] `estimators.py`: beta-binomial per `(theme, party)`; MoM + MLE option
- [x] Edge cases: n=0 prior-only; party n_members<3 → Beta(2,2) flagged
- [x] Derived JSON includes raw + EB fields listed in Prompt 2
- [x] Export party baselines (weighted / posterior mean) so frontend stops
      recomputing `median()`
- [x] Forest + compare default to EB; raw/shrunk toggle
- [x] Tests: shrinkage direction, high-n stability, CI width, synthetic RMSE

**Prompt 3 — methodology route**

- [x] `web/app/methodology/page.tsx` (or MDX) pulling live hyperparameters
      from derived JSON
- [x] Worked example from a real member cell
- [x] Changelog from `git log` of `data/votes.csv` + scoring module
- [x] “Reproduce this” command box

**Prompt 9 — design restraint** (can run after 2)

- [ ] Static forest annotations (name + delta, no hover required)
- [ ] Generated one-line takeaway per module
- [ ] OG image of annotated forest
- [ ] 375px: no horizontal scroll, 44px targets

**Prompt 5 — time**

- [x] Expanding-window EB series in derived JSON
- [x] Score-over-time module bound to existing `selectedId`
- [x] Biggest-mover 90d stat card

**Prompt 4 — IRT**

- [x] `analysis/irt_pipeline.py` PyMC 2PL; NUTS 4 chains; R-hat gate
- [x] Anchors config-driven (bioguide IDs, not names)
- [x] `data/derived/irt.json` + `make irt` + GHA on `votes.csv` change
- [x] Ideal-points module; discrimination on defection vote tooltips
- [x] Synthetic recovery test

**Prompt 6 — cosponsorship**

- [x] `data/bills_candidates.csv` HITL pattern
- [x] Reuse estimator module; never average with vote score
- [x] Hollow marker on forest; methodology sentence

**Prompt 10 — midterm race registry + FEC** (midterm kit)

- [x] `data/races.json` for VA-1 / VA-2 / VA-5 (2026-11-03, map_version=2021)
- [x] `vact races validate` + CI on ingest/publish
- [x] Dated OpenFEC snapshots `data/derived/fec_YYYYMMDD.json` (same-day no-op)
- [x] Build-time `days_until_election` on export / header countdown
- [x] `FEC_API_KEY` documented in `.env.example`

**Prompt 13 — seat model** (midterm kit)

- [x] Pre-registered `seat-v1.0` spec + OLS fundamentals + poll blend
- [x] Append-only `data/predictions_seats.csv` + CI validate
- [x] 2022 toss-up Brier vs always-incumbent in the fit summary
- [x] `/races` + `/races/[raceId]` probability, interval, decomposition, sparkline

**Prompt 14 — race pages + environment slider**

- [x] `/` battleground overview; `/race/va-0x` full race page; `/analysis` forest
- [x] Generic-ballot slider on a 0.5-point grid, client interpolation, scenario label
- [x] Flip-threshold takeaway sentences from the grid
- [x] Per-race OG images

**Prompt 17 — symmetry audit + blind coding** (midterm kit)

- [x] `VOTE_INCLUSION_SPEC.md` + `data/votes_excluded.csv` reason codes
- [x] `coded_blind` on `data/votes.csv`; `data/valence_review_queue.csv`
- [x] Five-metric audit in `vact audit symmetry` + methodology falsification section
- [x] Advocacy-verb lint + mirrored takeaway template tests
- [x] CI runs symmetry audit on ingest/publish

**Prompt 7 — forecasts**

- [ ] Append-only `data/predictions.csv` enforced in validation
- [ ] Brier vs party-line and base-rate; calibration plot
- [ ] `/forecasts` route

**Prompt 8 — editorial**

- [ ] Digest script + `/content/updates/YYYY-MM.md` drafts
- [ ] Snapshot derived JSON beside the note; no auto-publish

**Cutover hygiene (any time after 1)**

- [x] Publish workflow: `vact export-web` (or derived build) before assuming
      Vercel has fresh scores
- [x] Delete duplicated `median()` in `Dashboard.tsx` / `TargetProfiles.tsx`
      once baselines are in JSON
- [ ] Keep Sheets Yea/Nay scorecards labeled as a **different** metric so they
      are not mistaken for the signed axis

---

## 6. Assumptions

- Operative geography remains `map_version=2021` until Prompt 11-style numeric
  baselines replace `is_target` priors.
- Vercel stays JS-only. Python+PyMC stays GitHub Actions / local.
- `web/` is the activist-facing score UI; Sheets remains operator audit;
  `docs/` is legacy until explicitly retired.
- Prompt 1 acceptance “site renders identically” means Vercel `web/` signed
  scores, not the Sheets Yea/Nay cells.
