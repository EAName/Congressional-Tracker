"""Expanding-window empirical Bayes series (Prompt 5).

For each (member, theme), after every rollcall date that appears on that theme,
refit the (theme, party) prior from counts through that date and score the
member's accumulating (k, n). Last point equals the snapshot estimator because
the window has become the full sample.

as_of is the latest vote date in the input (or an explicit argument). Never
`datetime.now()` (backfill-hostile).

Nothing is persisted in DuckDB (AGENTS.md §8).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Sequence

from vact.analysis.estimators import BetaPrior, estimate_member_theme, fit_caucus_prior
from vact.analysis.scoring import ScoringConfig
from vact.analysis.votes import AxisDirection, VoteCast, VoteRow


def _iso(value: str) -> date:
    return date.fromisoformat(value[:10])


def _pro_increment(row: VoteRow) -> tuple[int, int] | None:
    """Return (k, n) for one contested vote, or None if it does not enter the score."""
    if row.vote_cast not in {VoteCast.YEA, VoteCast.NAY}:
        return None
    pro = (row.vote_cast is VoteCast.YEA and row.axis_direction is AxisDirection.ADVANCE) or (
        row.vote_cast is VoteCast.NAY and row.axis_direction is AxisDirection.OPPOSE
    )
    return (1 if pro else 0, 1)


def _fallback_prior(config: ScoringConfig) -> BetaPrior:
    return BetaPrior(
        alpha=config.eb_fallback_alpha,
        beta=config.eb_fallback_beta,
        source="weakly_informative",
        n_members=0,
    )


def _fit_priors(
    counts: dict[str, list[int]],
    party_of: dict[str, str | None],
    config: ScoringConfig,
) -> dict[str, BetaPrior]:
    grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for bio, (k, n) in counts.items():
        party = party_of.get(bio)
        if party and n > 0:
            grouped[str(party)].append((k, n))
    return {
        party: fit_caucus_prior(
            [k for k, _ in kns],
            [n for _, n in kns],
            method=config.eb_method,
            min_caucus=config.eb_min_caucus,
            fallback_alpha=config.eb_fallback_alpha,
            fallback_beta=config.eb_fallback_beta,
        )
        for party, kns in grouped.items()
    }


def _walk_theme(
    theme: str,
    by_date: dict[date, list[tuple[str, int, int]]],
    meta: dict[tuple[str, str], dict[str, Any]],
    cutoff: date,
    config: ScoringConfig,
    fallback: BetaPrior,
) -> dict[str, list[dict[str, Any]]]:
    """One theme: expanding counts, refit prior, emit a point per date with n>0."""
    dates = sorted(d for d in by_date if d <= cutoff)
    counts: dict[str, list[int]] = {}
    party_of: dict[str, str | None] = {}
    for (bio, t), info in meta.items():
        if t != theme:
            continue
        counts[bio] = [0, 0]
        party_of[bio] = info["party"]

    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in dates:
        for bio, k, n in by_date[d]:
            slot = counts.setdefault(bio, [0, 0])
            slot[0] += k
            slot[1] += n
            if bio not in party_of:
                party_of[bio] = meta.get((bio, theme), {}).get("party")
        priors = _fit_priors(counts, party_of, config)
        for bio, (k, n) in counts.items():
            if n == 0:
                continue
            party = party_of.get(bio)
            prior = priors.get(str(party), fallback) if party else fallback
            est = estimate_member_theme(k, n, prior, wilson_z=config.wilson_z)
            out[bio].append(
                {
                    "date": d.isoformat(),
                    "eb": est.eb_score,
                    "lo": est.cred_lo,
                    "hi": est.cred_hi,
                    "n": est.n,
                    "k": est.k,
                }
            )
    return out


def expanding_series(
    rows: Sequence[VoteRow],
    config: ScoringConfig,
    *,
    as_of: date | None = None,
    window_days: int | None = None,
) -> dict[str, Any]:
    """Build per-(member, theme) expanding-window EB series plus the 90d mover.

    Prior is refit at each theme-date from members' counts through that date
    (no look-ahead in α, β). Failure mode if we froze the full-sample prior:
    early points would use future caucus information.
    """
    window = int(window_days if window_days is not None else config.ts_window_days)
    if window < 1:
        raise ValueError("window_days must be >= 1")

    events_by_theme: dict[str, dict[date, list[tuple[str, int, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    max_date: date | None = None

    for row in rows:
        inc = _pro_increment(row)
        if inc is None:
            continue
        d = _iso(row.rollcall_date)
        max_date = d if max_date is None else max(max_date, d)
        k, n = inc
        events_by_theme[row.theme][d].append((row.member_bioguide_id, k, n))
        key = (row.member_bioguide_id, row.theme)
        if key not in meta:
            meta[key] = {
                "bioguide_id": row.member_bioguide_id,
                "full_name": row.member_name,
                "party": row.party or None,
                "chamber": row.chamber,
                "district_number": row.district_number,
                "theme": row.theme,
            }

    cutoff = as_of if as_of is not None else max_date
    if cutoff is None:
        return {
            "as_of": None,
            "window_days": window,
            "series": [],
            "biggest_mover": None,
        }

    fallback = _fallback_prior(config)
    series: list[dict[str, Any]] = []
    for theme, by_date in events_by_theme.items():
        walked = _walk_theme(theme, by_date, meta, cutoff, config, fallback)
        for bio, points in walked.items():
            info = meta[(bio, theme)]
            series.append({**info, "points": points})
    series.sort(key=lambda c: (c["theme"], c["bioguide_id"]))

    return {
        "as_of": cutoff.isoformat(),
        "window_days": window,
        "series": series,
        "biggest_mover": biggest_mover(
            series,
            as_of=cutoff,
            window_days=window,
            min_contested=config.min_contested,
        ),
    }


def _point_on_or_before(points: list[dict[str, Any]], cutoff: date) -> dict[str, Any] | None:
    chosen: dict[str, Any] | None = None
    for p in points:
        if _iso(p["date"]) <= cutoff:
            chosen = p
        else:
            break
    return chosen


def biggest_mover(
    series: Sequence[dict[str, Any]],
    *,
    as_of: date,
    window_days: int,
    min_contested: int,
) -> dict[str, Any] | None:
    """Largest |Δ EB| over [as_of − window, as_of] among cells sufficient at as_of.

    Start requires n≥1 so a first-vote appearance is not crowned a move.
    """
    start_cut = as_of - timedelta(days=window_days)
    ranked: list[tuple[float, int, str, str, dict[str, Any]]] = []
    for cell in series:
        points = cell["points"]
        if not points:
            continue
        end = _point_on_or_before(points, as_of)
        start = _point_on_or_before(points, start_cut)
        if end is None or start is None:
            continue
        if int(end["n"]) < min_contested or int(start["n"]) < 1:
            continue
        delta = float(end["eb"]) - float(start["eb"])
        ranked.append(
            (
                abs(delta),
                int(end["n"]),
                cell["bioguide_id"],
                cell["theme"],
                {
                    "bioguide_id": cell["bioguide_id"],
                    "full_name": cell["full_name"],
                    "party": cell.get("party"),
                    "chamber": cell.get("chamber"),
                    "district_number": cell.get("district_number"),
                    "theme": cell["theme"],
                    "delta": round(delta, 4),
                    "start_score": start["eb"],
                    "end_score": end["eb"],
                    "start_date": start["date"],
                    "end_date": end["date"],
                    "start_n": start["n"],
                    "end_n": end["n"],
                    "window_days": window_days,
                },
            )
        )
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][4]
