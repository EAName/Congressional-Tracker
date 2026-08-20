# About this project

## Who builds and maintains the site

The **Old Dominion Vote Index** (working title — final name TBD) is built and maintained by a small team of operators. Authorship and affiliations are disclosed here; they are not hidden in the site banner.

The engineering and data pipeline are version-controlled and public. Human reviewers adjudicate vote valence (axis direction) using a documented workflow. No adjudication row publishes until a human promotes it.

## Independence of the analysis

This site presents **independent analysis**, not campaign messaging. Scoring methodology applies identically to both parties. The estimator does not receive party identity as a score input — only as a shrinkage prior cell `(theme, party)`.

All adjudication decisions, source code, and derived data exports are public:

- [Methodology](/methodology) — formulas, hyperparameters, reproduction commands
- [Symmetry audit](/methodology#falsification) — pre-registered falsification metrics
- [GitHub repository](https://github.com/EAName/Congressional-Tracker) — full pipeline source
- [data/votes.csv](https://github.com/EAName/Congressional-Tracker/blob/main/data/votes.csv) — adjudication audit trail

## What we do not claim

We do not claim neutrality about which bills belong on the measured axis. Valence is a documented human judgment. We do claim that once valence is set, the arithmetic is party-blind and reproducible.

Counsel-reviewed disclaimer language for race pages may appear in `config/site_disclosure.yaml` when finalized.

## Contact

For corrections, see the [corrections policy](/corrections). For legal or compliance questions, see `COMPLIANCE_QUESTIONS.md` in the repository (questions for counsel, not answers).
