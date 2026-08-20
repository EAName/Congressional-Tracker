"""Automated symmetry and selection-bias audit (Prompt 17).

Party-blind arithmetic downstream of adjudication is assumed; this module
audits the human inclusion and axis-coding step where bias can enter.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import yaml

from vact.analysis.excluded_votes import EXCLUDED_PATH, load_excluded_csv
from vact.analysis.votes import VoteCast, VoteRow
from vact.paths import REPO_ROOT

SYMMETRY_CONFIG = REPO_ROOT / "config" / "symmetry_audit.yaml"
SPEC_PATH = REPO_ROOT / "src" / "vact" / "analysis" / "VOTE_INCLUSION_SPEC.md"


def load_symmetry_config(path: Path | None = None) -> dict[str, Any]:
    dest = path or SYMMETRY_CONFIG
    return yaml.safe_load(dest.read_text(encoding="utf-8")) or {}


def _norm_party(party: str) -> str | None:
    p = (party or "").strip().lower()
    if p in {"democrat", "d"}:
        return "Democrat"
    if p in {"republican", "r"}:
        return "Republican"
    return None


def _caucus_majority_advancing(
    rows: Sequence[VoteRow],
    *,
    party: str,
) -> bool | None:
    subset = [
        r
        for r in rows
        if r.contested and _norm_party(r.party) == party
    ]
    if not subset:
        return None
    yea = sum(1 for r in subset if r.vote_cast is VoteCast.YEA)
    nay = sum(1 for r in subset if r.vote_cast is VoteCast.NAY)
    if yea == nay:
        return None
    majority_yea = yea > nay
    axis = subset[0].axis_direction.value
    if axis == "advance":
        return majority_yea
    return not majority_yea


def caucus_advancing_by_theme(rows: Sequence[VoteRow]) -> list[dict[str, Any]]:
    """Share of roll calls where each caucus majority advanced the axis."""
    by_roll: dict[tuple[str, str], list[VoteRow]] = defaultdict(list)
    for row in rows:
        by_roll[(row.rollcall_id, row.theme)].append(row)
    theme_stats: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {"Democrat": [], "Republican": []}
    )
    for (_rid, theme), group in by_roll.items():
        for party in ("Democrat", "Republican"):
            flag = _caucus_majority_advancing(group, party=party)
            if flag is not None:
                theme_stats[theme][party].append(flag)
    out = []
    for theme in sorted(theme_stats):
        dem = theme_stats[theme]["Democrat"]
        rep = theme_stats[theme]["Republican"]
        dem_share = sum(dem) / len(dem) if dem else None
        rep_share = sum(rep) / len(rep) if rep else None
        gap = None
        if dem_share is not None and rep_share is not None:
            gap = round(100.0 * (dem_share - rep_share), 1)
        note = (
            "A lopsided share means that caucus's floor majority more often voted "
            "with the coded axis direction on that theme. It does not by itself "
            "prove biased adjudication."
        )
        out.append(
            {
                "theme": theme,
                "n_rollcalls_dem": len(dem),
                "n_rollcalls_rep": len(rep),
                "dem_caucus_advancing_share": None if dem_share is None else round(dem_share, 3),
                "rep_caucus_advancing_share": None if rep_share is None else round(rep_share, 3),
                "gap_pp": gap,
                "note": note,
            }
        )
    return out


def n_depth_by_party(scores: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_party: dict[str, list[int]] = defaultdict(list)
    for row in scores:
        party = row.get("party")
        if not party:
            continue
        n = int(row.get("n") or row.get("n_contested") or 0)
        if n <= 0:
            continue
        by_party[str(party)].append(n)
    summary = {}
    for party, vals in sorted(by_party.items()):
        summary[party] = {
            "n_cells": len(vals),
            "median": statistics.median(vals),
            "min": min(vals),
            "max": max(vals),
        }
    medians = [summary[p]["median"] for p in summary]
    gap = abs(medians[0] - medians[1]) if len(medians) == 2 else None
    return {"by_party": summary, "median_gap": gap}


def ci_width_at_matched_n(scores: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare EB credible width at equal n_contested."""
    buckets: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in scores:
        party = row.get("party")
        if party not in {"Democrat", "Republican"}:
            continue
        n = int(row.get("n") or row.get("n_contested") or 0)
        lo, hi = row.get("cred_lo"), row.get("cred_hi")
        if n < 1 or lo is None or hi is None:
            continue
        buckets[n][str(party)].append(float(hi) - float(lo))
    rows = []
    for n in sorted(buckets):
        dem = buckets[n].get("Democrat") or []
        rep = buckets[n].get("Republican") or []
        if len(dem) < 2 or len(rep) < 2:
            continue
        dem_med = statistics.median(dem)
        rep_med = statistics.median(rep)
        rows.append(
            {
                "n_contested": n,
                "dem_median_width": round(dem_med, 4),
                "rep_median_width": round(rep_med, 4),
                "gap": round(abs(dem_med - rep_med), 4),
            }
        )
    return rows


def exclusion_by_sponsor_party(excluded: Sequence[dict[str, str]]) -> dict[str, Any]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for row in excluded:
        party = row.get("sponsor_party") or "Unknown"
        totals[party] += 1
        counts[party][row.get("reason_code") or "OTHER"] += 1
    dem = totals.get("Democrat", 0)
    rep = totals.get("Republican", 0)
    dem_total = dem + rep
    gap = None
    if dem_total > 0:
        dem_rate = 100.0 * dem / dem_total
        rep_rate = 100.0 * rep / dem_total
        gap = round(abs(dem_rate - rep_rate), 1)
    return {
        "totals_by_sponsor_party": dict(totals),
        "by_reason": {p: dict(c) for p, c in counts.items()},
        "democrat_share_pp": round(100.0 * dem / dem_total, 1) if dem_total else None,
        "rate_gap_pp": gap,
    }


def coded_blind_audit(rows: Sequence[VoteRow]) -> dict[str, Any]:
    by_unit: dict[tuple[str, str], bool] = {}
    for row in rows:
        key = (row.rollcall_id, row.theme)
        blind = getattr(row, "coded_blind", False)
        prior = by_unit.get(key)
        if prior is not None and prior != blind:
            raise ValueError(f"inconsistent coded_blind for {key}")
        by_unit[key] = blind
    if not by_unit:
        return {"n_units": 0, "false_share": None, "false_share_pp": None}
    false_n = sum(1 for v in by_unit.values() if not v)
    share = false_n / len(by_unit)
    return {
        "n_units": len(by_unit),
        "false_count": false_n,
        "false_share": round(share, 4),
        "false_share_pp": round(100.0 * share, 1),
    }


def _tripped(value: float | None, threshold: float) -> bool:
    if value is None:
        return False
    return abs(value) > threshold


def build_symmetry_audit(
    vote_rows: Sequence[VoteRow],
    scores: Sequence[dict[str, Any]],
    *,
    excluded: Sequence[dict[str, str]] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_symmetry_config()
    thresholds = cfg.get("thresholds") or {}
    excluded_rows = list(excluded) if excluded is not None else load_excluded_csv()

    caucus = caucus_advancing_by_theme(vote_rows)
    max_gap = max((abs(r["gap_pp"]) for r in caucus if r.get("gap_pp") is not None), default=0.0)
    depth = n_depth_by_party(scores)
    ci = ci_width_at_matched_n(scores)
    max_ci_gap = max((r["gap"] for r in ci), default=0.0)
    excl = exclusion_by_sponsor_party(excluded_rows)
    blind = coded_blind_audit(vote_rows)

    reason_counts = Counter(r.get("reason_code") or "OTHER" for r in excluded_rows)

    flags = {
        "caucus_advancing_gap": _tripped(
            max_gap, float(thresholds.get("caucus_advancing_gap_pp", 25))
        ),
        "n_depth_median_gap": _tripped(
            depth.get("median_gap"), float(thresholds.get("n_depth_median_gap", 2))
        ),
        "ci_width_gap_at_matched_n": _tripped(
            max_ci_gap, float(thresholds.get("ci_width_gap_at_matched_n", 0.08))
        ),
        "exclusion_rate_gap_pp": _tripped(
            excl.get("rate_gap_pp"), float(thresholds.get("exclusion_rate_gap_pp", 10))
        ),
        "coded_blind_false_share_pp": _tripped(
            blind.get("false_share_pp"), float(thresholds.get("coded_blind_false_share_pp", 5))
        ),
    }

    return {
        "inclusion_spec_version": cfg.get("inclusion_spec_version"),
        "spec_path": str(SPEC_PATH.relative_to(REPO_ROOT)),
        "excluded_path": str(EXCLUDED_PATH.relative_to(REPO_ROOT)),
        "excluded_counts_by_reason": dict(reason_counts),
        "caucus_advancing_by_theme": caucus,
        "max_caucus_advancing_gap_pp": max_gap,
        "n_depth_by_party": depth,
        "ci_width_at_matched_n": ci,
        "max_ci_width_gap": max_ci_gap,
        "exclusion_by_sponsor_party": excl,
        "coded_blind": blind,
        "thresholds": thresholds,
        "falsification": cfg.get("falsification") or {},
        "flags": flags,
        "any_tripped": any(flags.values()),
    }


def validate_excluded_append_only(current: Sequence[dict[str, str]]) -> None:
    """Excluded file is rewritten wholesale; ensure required columns."""
    required = {"vote_id", "reason_code"}
    for row in current:
        if not required <= set(row):
            raise ValueError(f"excluded row missing columns: {row}")
