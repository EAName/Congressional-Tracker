# VA Congressional Tracker

Idempotent roll-call warehouse for the Virginia House/Senate delegation, built to
support DPVA / Small Business Caucus outreach. v1 froze dashboard metrics while
votes grew underneath; v2 recomputes every published number at render / export
time from DuckDB.

Audience: operators and engineers. Agent invariants live in [`AGENTS.md`](AGENTS.md)
— treat that as load-bearing, not prose.

## Architecture

```
clerk.house.gov / senate.gov / congress-legislators / congress.gov
        │  httpx + tenacity (shared UA; senate rejects python-httpx)
        ▼
data/raw/{source}/{yyyy}/{id}.{ext}     ← immutable; parse never hits network
        │
        ▼
DuckDB  data/warehouse/warehouse.duckdb
  dim_legislator (VA SCD2) · dim_district (map_version 2021|2026)
  dim_bill · fact_vote · fact_member_vote · bridge_vote_impact
  fact_vote_valence                     ← political judgment in; scores out live
        │
        ├── classify / promote          impact tags (RULE|HUMAN; LLM never publishes)
        ├── build_scores_frame          signed ∈ [-1,+1] + Wilson band (no persist)
        ├── compute_party_deviations    within-caucus defections
        └── exports
              Sheets  audit workbook
              docs/   static activist site (legacy Pages path)
              web/    Next.js dashboard → Vercel (build-time JSON)
```

Natural keys everywhere. Re-ingest of a roll call is byte-identical on disk and
does not duplicate warehouse rows. Join key for legislators is `bioguide_id`
only; Senate `lis_member_id` resolves through a national crosswalk, then hard-fails
on unresolved IDs (VA-only `dim_legislator` cannot cover a 100-member roll).

**Failure mode this prevents:** silent member mis-attribution and non-replayable
transforms after upstream markup drift.

## Stack

| Layer | Choice | Rejected |
|---|---|---|
| Warehouse | DuckDB single-file | Postgres (ops overhead at this scale) |
| Frames | Polars where needed | Pandas (AGENTS §5) |
| Contracts | Pydantic v2 | ad-hoc dicts |
| CLI | Typer via `./bin/vact` | bare scripts |
| Package mgmt | `uv` | pip-tools |
| Activist UI | Next.js 15 static in `web/` on Vercel | live DB; server render of DuckDB |
| Audit UI | Google Sheets (`VACT_SHEETS_*`) | — |

Corpus size for the 119th is well under a gigabyte. The DuckDB→Postgres migration
path is mechanical if multi-writer ever appears.

## Map versions

Every geography-bearing query names `map_version`:

- **`2021`** — court-drawn / operative for scoring, deviations, Sheets Dashboard,
  `web/` export. Targets: VA-1, VA-2 (`config/districts.yaml`).
- **`2026`** — HB29 proposed (nullified 2026-05-08). Retained for contrast; do not
  mix with 2021 scores.

District numbers persist across versions; lean and `is_target` do not. Mixing maps
attributes votes to the wrong electorate.

## Scoring frame (analysis substrate)

Configured in `config/scoring.yaml`. Live only — never written to the warehouse.

- Scoreable = passage/amendment ∩ adjudicated valence `±1`. Procedural / cloture /
  nomination / suspension / MTR stay out of the likelihood.
- Member-theme cell is `sufficient` at `n_contested ≥ sufficiency.min_contested`
  (default 3). `NOT_VOTING`/`PRESENT` → `absence_rate`, never imputed as Nay.
- Signed score = \(2\hat{p}_{\text{pro}} - 1\) with Wilson band at configured \(z\).
- Within-party deviation = member score − weighted-median caucus baseline among
  `sufficient` peers; defection votes are roll calls where member axis direction
  opposed the party majority on that vote.

Valence proposals (`vact valence propose`) write as `RULE` / `PROPOSAL`. Promote to
`HUMAN` before treating a scorecard as publication-grade. Publication-facing
surfaces (`docs/`, briefs) additionally require `plain_language_summary` and refuse
unadjudicated `LLM` tags — `web/` currently does **not** enforce that gate; treat
it as analysis UI until wired.

## Surfaces

| Surface | Command | Notes |
|---|---|---|
| Sheets audit | `vact sheets push` | Never clear-before-write. OAuth or SA. |
| Legacy static | `vact site` → `docs/` | Publication-gated votes. |
| Vercel dashboard | `vact export-web` → `web/data/*.json` | Build-time import; Root Directory = `web` |
| Social cards | `vact social` | 1200×675 Target seats |

Sheet: [VA Congressional Vote Tracker](https://docs.google.com/spreadsheets/d/1fbjfNKB79-Rzq70X9Ixg67aVzxYmv6nxxj-hCVQDyi0).
Repo: [EAName/Congressional-Tracker](https://github.com/EAName/Congressional-Tracker).

## Local loop

```bash
uv sync && uv pip install -e .
./bin/vact dimensions          # legislators + districts
./bin/vact incremental         # raw → warehouse
./bin/vact classify --new-only --no-llm
./bin/vact valence propose     # RULE proposals; review + valence set
./bin/vact votes export        # warehouse → versioned data/votes.csv
./bin/vact votes validate
./bin/vact score --write       # reads votes.csv when present
./bin/vact deviations
./bin/vact export-web          # refresh web/data for Vercel (from votes.csv)
./bin/vact cosp fetch          # Congress.gov (co)sponsorship → bills_candidates.csv
./bin/vact cosp validate
uv sync --extra irt && ./bin/vact irt   # offline 2PL → data/derived/irt.json
make test
```

Sheets:

```bash
export VACT_SHEETS_AUTH=oauth
export VACT_SHEETS_ID=1fbjfNKB79-Rzq70X9Ixg67aVzxYmv6nxxj-hCVQDyi0
export VACT_SHEETS_OAUTH_CLIENT=./secrets/oauth_client.json
export VACT_SHEETS_OAUTH_TOKEN=./secrets/authorized_user.json
./bin/vact sheets preflight && ./bin/vact sheets push
```

Web:

```bash
cd web && npm ci && npm run dev   # http://localhost:3000
```

Vercel: import the GitHub repo, set **Root Directory** to `web`. The Publish
workflow validates `data/votes.csv` and runs `vact export-web` (Python stays off
Vercel). Commit `data/votes.csv` is the scoring audit trail (`git log -- data/votes.csv`).

## CI shape

Tiered Actions under `.github/workflows/`:

1. **Ingest** (Tue–Sat) — incremental pull
2. **Dimensions** (Mon) — roster / district refresh
3. **Publish** (Mon after Dimensions) — site + gaps + `export-web`; refuses red Dimensions / recent
   failed Ingest

Notifications fire only on pipeline contract failure or new tagged VA party-line
splits — silent no-ops when incremental finds no content change.

## Layout

```
src/vact/
  sources/      fetch/parse only
  models/       Pydantic contracts
  warehouse/    DDL, load, migrations
  transforms/   dims, classify
  analysis/     scoring, deviations
  exports/      sheets, site, social, web JSON
config/         impact_rules.yaml, scoring.yaml, districts.yaml
sql/            DDL + analytic SQL as files
web/            Next.js presentation (Vercel)
docs/           generated static site (Pages-era)
tests/          pytest + pytest-httpx
data/raw/       gitignored landing zone
data/warehouse/ gitignored DuckDB
```

## Contracts worth knowing

- Member totals on a roll call must reconcile to source XML or the load fails
  (`vact contracts` / `tests/test_contracts.py`).
- Non-VA members appear in `fact_member_vote` without a `dim_legislator` row by
  design (Senate-wide rolls).
- No computed metric is stored. If a export needs a number, it queries live.
  Persisting a frozen scorecard is how v1 went stale at 55 votes.

## Open / known debt

- Adjudication throughput: most tagged votes still lack `plain_language_summary`.
- Prompt 11 numeric 2021 baselines (PVI/VPAP) not yet in; VA-1/VA-2 targets are
  political priors in `districts.yaml`.
- Publish workflow still commits `docs/`; Vercel cutover needs `export-web` wired
  and Pages retired when ready.
