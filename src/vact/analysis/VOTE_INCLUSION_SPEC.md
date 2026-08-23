# Vote inclusion spec — `vote-inclusion-v1.1`

Frozen 2026-08-19. This file pre-registers which roll calls may enter the
signed score before outcomes are examined. Changes bump `version` in
`config/symmetry_audit.yaml` and log a reason below.

## Estimand

A `(vote_id, impact_tag)` pair is **eligible for scoring** when it passes every
gate below. Eligibility is decided without looking at how Virginia members voted.

## Inclusion gates (all required)

1. **Category**: `vote_category` is in `scoreable.include_categories` from
   `config/scoring.yaml` (currently PASSAGE, AMENDMENT, SUSPENSION).
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
| `NEAR_UNANIMOUS` | ≥95% of contested chamber positions on the same side. **Reported, not enforced** — see below. |
| `UNADJUDICATED_DIRECTION` | Impact tag present but no adjudicated valence ±1 |
| `NO_IMPACT_TAG` | No bridge row (classification queue) |
| `OTHER` | Reserved. Not currently emitted by `excluded_votes.py`; if used, document in `notes`. |

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
| vote-inclusion-v1.1 | 2026-08-22 | Add SUSPENSION to `include_categories` | Small-business bills are disproportionately bipartisan and move on the suspension calendar: PPP Flexibility, PPP Extension, Microloan Improvement, SBA 7(a) Transparency were all unreachable. 70 tagged suspension pairs become eligible; none carry an adjudicated valence, so no published score moves on the bump itself. **Known divergence:** `NEAR_UNANIMOUS` is emitted by the exclusions report but is not enforced in the scoring path (`h-119-1-15/TAX_BURDEN` is labelled excluded yet contributes 10 scored member rows). Enforcing it would remove most of what this bump adds. |
