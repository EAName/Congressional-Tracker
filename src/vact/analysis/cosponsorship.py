"""Cosponsorship affinity scores (Prompt 6).

Among adjudicated theme bills a member (co)sponsored:
  n = those bills
  k = those with axis_direction=advance

That is the vote analog of a taken position. Silence is not a NAY.

Uses estimate_member_theme / fit_caucus_prior. Never averaged with floor scores.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from vact.analysis.bills_candidates import BillCandidate, load_candidates
from vact.analysis.estimators import attach_empirical_bayes
from vact.analysis.scoring import ScoringConfig, load_scoring_config, signed_score_from_counts
from vact.analysis.votes import AxisDirection, load_votes_csv
from vact.paths import REPO_ROOT

ACTIONS_PATH = REPO_ROOT / "data" / "cosponsor_actions.csv"
ACTIONS_COLUMNS = ("member_bioguide_id", "bill_id", "role", "member_name", "party", "chamber", "district")


def write_actions(rows: Sequence[dict[str, str]], path: Path | None = None) -> Path:
    dest = path or ACTIONS_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r["bill_id"], r["member_bioguide_id"]))
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ACTIONS_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            writer.writerow({col: row.get(col, "") for col in ACTIONS_COLUMNS})
    return dest


def load_actions(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or ACTIONS_PATH
    if not dest.is_file():
        return []
    with dest.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in rec.items()} for rec in csv.DictReader(fh)]


def merge_actions(existing: Sequence[dict[str, str]], incoming: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Natural key (member, bill_id). Sponsor wins over cosponsor."""
    rank = {"sponsor": 1, "cosponsor": 0}
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in [*existing, *incoming]:
        key = (row["member_bioguide_id"], row["bill_id"])
        prior = by_key.get(key)
        if prior is None or rank.get(row.get("role", ""), 0) >= rank.get(prior.get("role", ""), 0):
            by_key[key] = dict(row)
    return list(by_key.values())


def _members_from_votes(votes_path: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        rows = load_votes_csv(votes_path)
    except FileNotFoundError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out.setdefault(
            row.member_bioguide_id,
            {
                "bioguide_id": row.member_bioguide_id,
                "full_name": row.member_name,
                "party": row.party or None,
                "chamber": row.chamber,
                "district_number": row.district_number,
            },
        )
    return out


def build_cosponsor_frame(
    candidates: Sequence[BillCandidate],
    actions: Sequence[dict[str, str]],
    members: dict[str, dict[str, Any]],
    config: ScoringConfig | None = None,
) -> list[dict[str, Any]]:
    """One row per (member, theme) with n>0. Same EB attach as votes."""
    cfg = config or load_scoring_config()
    bills = [
        c
        for c in candidates
        if c.adjudicated and c.axis_direction in {AxisDirection.ADVANCE.value, AxisDirection.OPPOSE.value}
    ]
    bills_by_id: dict[str, list[BillCandidate]] = defaultdict(list)
    for c in bills:
        bills_by_id[c.bill_id].append(c)

    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for act in actions:
        bio = act.get("member_bioguide_id") or ""
        if bio not in members:
            continue
        for cand in bills_by_id.get(act.get("bill_id") or "", []):
            key = (bio, cand.theme)
            rec = counts.get(key)
            if rec is None:
                rec = {
                    **members[bio],
                    "impact_tag": cand.theme,
                    "n_contested": 0,
                    "n_pro": 0,
                    "n_yea": 0,
                    "n_nay": 0,
                    "n_not_voting": 0,
                    "n_present": 0,
                }
                counts[key] = rec
            rec["n_contested"] += 1
            if cand.axis_direction == AxisDirection.ADVANCE.value:
                rec["n_pro"] += 1
                rec["n_yea"] += 1
            else:
                rec["n_nay"] += 1

    if not counts:
        return []

    frame: list[dict[str, Any]] = []
    for rec in counts.values():
        n = int(rec["n_contested"])
        k = int(rec["n_pro"])
        raw = signed_score_from_counts(k, n, cfg.wilson_z)
        rec["signed_score"] = raw["signed_score"]
        rec["wilson_low"] = raw["wilson_low"]
        rec["wilson_high"] = raw["wilson_high"]
        rec["sufficient"] = n >= cfg.min_contested
        rec["absence_rate"] = 0.0
        rec["map_version"] = "2021"
        frame.append(rec)

    out, _baselines = attach_empirical_bayes(frame, cfg)
    return out


def score_cosponsorship(
    *,
    candidates_path: Path | None = None,
    actions_path: Path | None = None,
    votes_path: Path | None = None,
    extra_members: Sequence[dict[str, Any]] | None = None,
    config: ScoringConfig | None = None,
) -> list[dict[str, Any]]:
    members = _members_from_votes(votes_path)
    for extra in extra_members or []:
        bio = str(extra["bioguide_id"])
        members.setdefault(
            bio,
            {
                "bioguide_id": bio,
                "full_name": extra.get("full_name") or bio,
                "party": extra.get("party"),
                "chamber": extra.get("chamber") or "Senate",
                "district_number": extra.get("district_number"),
            },
        )
    return build_cosponsor_frame(
        load_candidates(candidates_path),
        load_actions(actions_path),
        members,
        config,
    )


def serialize_cosponsor_rows(frame: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "bioguide_id": r["bioguide_id"],
            "full_name": r["full_name"],
            "party": r.get("party"),
            "chamber": r.get("chamber"),
            "district_number": r.get("district_number"),
            "theme": r["impact_tag"],
            "eb_score": r["eb_score"],
            "cred_lo": r["cred_lo"],
            "cred_hi": r["cred_hi"],
            "raw_score": r["raw_score"],
            "n": r["n"],
            "k": r["k"],
            "prior_source": r["prior_source"],
            "sufficient": r["sufficient"],
        }
        for r in frame
        if r.get("eb_score") is not None
    ]
