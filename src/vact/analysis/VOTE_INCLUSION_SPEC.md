# Vote inclusion spec — `vote-inclusion-v1.0`

Frozen 2026-08-19. This file pre-registers which roll calls may enter the
signed score before outcomes are examined. Changes bump `version` in
`config/symmetry_audit.yaml` and log a reason below.

## Estimand

A `(vote_id, impact_tag)` pair is **eligible for scoring** when it passes every
gate below. Eligibility is decided without looking at how Virginia members voted.

## Inclusion gates (all required)

1. **Category**: `vote_category` is in `scoreable.include_categories` from
   `config/scoring.yaml` (currently PASSAGE, AMENDMENT).
2. **Impact tag**: at least one row in `bridge_vote_impact` for the vote.
3. **Valence adjudicated**: `fact_vote_valence` carries `valence ∈ {-1, +1}` with
   source HUMAN (RULE/LLM proposals do not publish until promoted).
4. **Not a special-order rule resolution**: excluded when
   `exclude_rule_resolutions` matches bill type + title pattern in scoring.yaml.

## Exclusion reason codes (`data/votes_excluded.csv`)

| code | meaning |
|------|---------|
| `PROCEDURAL_CATEGORY` | Category in `exclude_categories` (CLOTURE, NOMINATION, …) |
| `RULE_RESOLUTION` | Special-order H/S Res matching the configured title pattern |
| `NEAR_UNANIMOUS` | ≥95% of contested chamber positions on the same side (YEA or NAY) |
| `UNADJUDICATED_DIRECTION` | Impact tag present but no adjudicated valence ±1 |
| `NO_IMPACT_TAG` | No bridge row (classification queue) |
| `OTHER` | Documented in `notes` column |

Near-unanimous uses the full roll call in `fact_member_vote`, not VA-only rows.
That catches consensus technical votes that would not discriminate caucuses.

## Blind axis coding

Operators set `axis_direction` / valence without seeing caucus breakdowns.
Committed rows in `data/votes.csv` carry `coded_blind=true` when adjudicated
through `data/valence_review_queue.csv` (no party columns). Rows coded after
seeing member positions must set `coded_blind=false`; the symmetry audit reports
their share.

## Changelog

| version | date | change | reason |
|---------|------|--------|--------|
| vote-inclusion-v1.0 | 2026-08-19 | Initial freeze | Prompt 17 pre-registration |
