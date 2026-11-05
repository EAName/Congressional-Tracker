# Post-election review, 2026 cycle

Written 2026-11-05 against unofficial returns. Every figure below is reproduced by
`./bin/vact score-forecasts`, which recomputes from `data/election_results_2026.csv`
and the published payloads in `web/data/`. Nothing here is a stored metric
(AGENTS.md section 8), so a canvass correction changes the score rather than
contradicting it.

The scored forecast is the one the public saw: the final deploy of 2026-10-27,
`seat-v1.1` for the eleven House races and `senate-v0.1` for VA-Sen. It is not
`data/predictions_seats.csv`, which stopped being written at `seat-v1.0` in August.

## Result

Ten of twelve winners called. The two misses were VA-1, forecast at 49.8% Democratic
and won by Taylor, and VA-5, forecast at 64.6% and won by McGuire.

| subset | n | Brier | winners | share MAE | bias |
|---|---|---|---|---|---|
| all | 12 | 0.0649 | 10/12 | 2.5 pp | +2.1 pp |
| competitive (5-95%) | 5 | 0.1553 | 3/5 | 2.4 pp | +1.9 pp |
| safe | 7 | 0.0004 | 7/7 | 2.5 pp | +2.3 pp |

Baselines: always-incumbent 0.1667, coin flip 0.2500, 2024 presidential lean 6.7 pp
share MAE.

## What held

Vote share. 2.5 points of mean absolute error against 6.7 for presidential lean is
2.7x the naive baseline, and it is the result that survives the small sample best.

Calibration at the extremes. Seven calls at 95% or above, or 5% or below, including
several at 99.9%. None was wrong.

## What did not

**Competitive races barely beat the trivial baseline.** 0.1553 against 0.1667 for
assuming every incumbent holds. On the only five races that needed a forecast, the
model earned almost nothing over a rule requiring no model at all. The headline
0.0649 is carried by safe seats.

**A systematic Democratic bias of 2.1 points, in 9 of 12 races.** One-directional
error on that scale is not sampling noise. The likely source is the national
environment: `nat_env` enters district mu with a coefficient frozen at 1.0, so a
generic-ballot average roughly 2 to 3 points too Democratic reproduces the pattern.
Untested as of writing, because the national House popular vote was not yet
available and early counts understate Democrats while California, Washington and
Arizona are still counting. Re-run this review when that number exists.

**Excluding district polls was the costliest call of the cycle, and it was wrong.**
Three public polls covered races we model. All three were excluded for failing the
archive's metadata bar, and separately because `blend_mu` would have weighted them at
roughly 92% against the fundamentals.

| race | poll | poll error | poll call | our error | our call |
|---|---|---|---|---|---|
| VA-1 | WaPo/Schar | 0.9 pp | correct | 1.2 pp | MISS |
| VA-2 | CNU Wason | 2.7 pp | correct | 2.4 pp | correct |
| VA-5 | WaPo/Schar | 2.0 pp | correct | 4.2 pp | MISS |

The polls were more accurate in aggregate (1.9 pp against 2.6 pp) and called all
three correctly, against our one of three. A sensitivity run indicates that
including them, even through the blend criticised as overconfident, would have
produced twelve of twelve.

The statistical objection to `blend_mu` stands: weighting a 600-respondent poll at
92% against the fundamentals is wrong in general and would be punished in a cycle
where district polls miss. But that argued for fixing the blend, not for discarding
the only direct evidence about three races. The caution was aimed at the right
target and applied to the wrong object.

## Carried into the next cycle

1. Add non-sampling error to district polls in `blend_mu`, pre-registered as a spec
   bump, then admit published district polls by default. The present blend treats a
   district poll as roughly three times more informative than it is.
2. Re-score against the national House popular vote and test whether the national
   environment explains the 2.1 point bias. If it does, the question becomes whether
   `nat_env` should keep a coefficient of 1.0.
3. Record metadata gaps as their own category rather than silent exclusions. CBS
   publishes no likely-voter subgroup n because its likely-voter screen is a
   continuous weight; the WaPo/Schar district polls publish no n at all. A rule that
   drops any poll missing one field drops good polls.
4. Harvard-Harris was excluded all cycle on question-format grounds and was the one
   poll consistently pulling the average toward what turned out to be the right
   direction.

## Caveats

Returns are unofficial and pre-canvass. VA-5 is the cautionary case: Perriello led by
1.3 points with 23 of 24 localities on election night and lost by 2.2 once the last
one reported. Twelve races in one state cannot establish how this model compares to
published forecasters; a single different outcome in VA-5 moves the competitive
Brier by 60%. The honest next test is all 435 districts, or the leave-one-cycle-out
cross-validation the repo already supports.
