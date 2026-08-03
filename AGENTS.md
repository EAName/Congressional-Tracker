# AGENTS.md — VA Congressional Tracker

Non-negotiable rules for every contributor and coding agent working in this repo.
Violate these and the ingest is not trustworthy.

## 1. Idempotent ingest

Every ingest is idempotent. Re-running a fetch for the same roll call must produce
byte-identical output and must not duplicate warehouse rows. Use natural keys, not
autoincrement surrogates.

## 2. Raw before parse

Raw payloads land unmodified in `data/raw/{source}/{yyyy}/{identifier}.{ext}` before
any parsing. Parsing reads from disk, never from the network. This makes every
transform replayable without re-hitting upstream.

## 3. `bioguide_id` is the only legislator join key

`bioguide_id` is the sole legislator join key across the entire codebase. No name
matching, no fuzzy joins, no district-based lookups. If a source lacks
`bioguide_id`, resolve it through the crosswalk dimension and fail loudly if
resolution is ambiguous.

## 4. Single HTTP client factory

All network calls go through a single `httpx` client factory with tenacity retry
(exponential backoff, max 5 attempts) and a descriptive User-Agent. `senate.gov`
rejects the default `python-httpx` agent.

## 5. No pandas

No pandas. Use polars for dataframes and DuckDB for anything relational.

## 6. `fetch()` and `parse()` stay separate

Every source module exposes `fetch()` and `parse()` as separate functions. Never
combine them.

## 7. Timestamp and date types

Timestamps are stored as UTC ISO 8601. Vote dates are stored as `DATE`, not `TEXT`.

## 8. No persisted summary metrics

No computed metric is ever persisted as a stored value. Every count in every export
is a live query at render time. (v1 Dashboard froze at 55 votes while the Votes tab
grew to 341.)

## Stack

- Python 3.11+
- `uv` for dependency management
- DuckDB warehouse (`data/warehouse/warehouse.duckdb`)
- Pydantic v2 source contracts
- Typer CLI (`./bin/vact` or `python -m vact`)
- pytest (+ pytest-httpx)

## Package layout

```
src/vact/
  sources/       # one module per upstream API, no transformation logic
  models/        # Pydantic contracts for every source payload
  warehouse/     # DuckDB DDL, load functions, migrations
  transforms/    # dimensional modeling, classification
  exports/       # Sheets (audit), static site, social cards
  cli.py         # Typer entrypoint
config/          # impact rules, plain-language workflow inputs
docs/            # generated static site (GitHub Pages)
sql/             # DDL and analytic queries as .sql files
tests/
data/raw/        # gitignored landing zone
data/warehouse/  # gitignored DuckDB file
data/reports/    # coverage / review artifacts (committed when green)
data/legacy/v1/  # frozen v1 spreadsheet exports (reference only)
```

## Senate LIS resolution

`dim_legislator` is Virginia-scoped SCD2. Senate roll calls include 100 members, so
`lis_member_id → bioguide_id` resolves through a national crosswalk built from
congress-legislators (not VA-only `dim_legislator` rows). Unresolved IDs hard-fail.

## Sequencing

Build order is defined by the Prompt Kit (prompts 0–10). Do not skip ahead of the
critical path (prompts 1–4) when adding warehouse-dependent logic.
