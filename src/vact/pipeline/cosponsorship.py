"""Fetch Congress.gov (co)sponsorship lists and merge HITL candidate bills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vact.analysis.bills_candidates import (
    CANDIDATES_PATH,
    merge_candidates,
    propose_from_bills,
    validate_candidates,
    write_candidates,
    load_candidates,
    CandidatesError,
)
from vact.analysis.cosponsorship import load_actions, merge_actions, write_actions
from vact.analysis.scoring import load_scoring_config
from vact.http_client import create_client
from vact.paths import REPO_ROOT
from vact.sources.cosponsorship import (
    BillRef,
    fetch_member_legislation,
    parse_member_legislation,
    raw_member_page_path,
)

CONFIG_PATH = REPO_ROOT / "config" / "cosponsorship.yaml"


def load_cosp_config(path: Path | None = None) -> dict[str, Any]:
    payload = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
    return payload


def _member_meta_from_votes_and_config(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    from vact.analysis.votes import load_votes_csv, VOTES_CSV_PATH

    out: dict[str, dict[str, str]] = {}
    if VOTES_CSV_PATH.is_file():
        for row in load_votes_csv(VOTES_CSV_PATH):
            out.setdefault(
                row.member_bioguide_id,
                {
                    "member_bioguide_id": row.member_bioguide_id,
                    "member_name": row.member_name,
                    "party": row.party,
                    "chamber": row.chamber,
                    "district": row.district,
                },
            )
    for extra in cfg.get("extra_members") or []:
        bio = str(extra["bioguide_id"])
        out.setdefault(
            bio,
            {
                "member_bioguide_id": bio,
                "member_name": str(extra.get("full_name") or bio),
                "party": str(extra.get("party") or ""),
                "chamber": str(extra.get("chamber") or "Senate"),
                "district": str(extra.get("district") or ""),
            },
        )
    return out


def _parse_cached(congress: int, bioguide_id: str, kind: str) -> list[BillRef]:
    paths = []
    offset = 0
    while True:
        path = raw_member_page_path(congress, bioguide_id, kind, offset)  # type: ignore[arg-type]
        if not path.is_file():
            break
        paths.append(path)
        offset += 250
        if offset > 20_000:
            break
    return parse_member_legislation(paths) if paths else []


def ingest_cosponsorship(
    *,
    api_key: str | None,
    congress: int | None = None,
    force: bool = False,
    from_raw: bool = False,
) -> dict[str, Any]:
    """Fetch (unless from_raw), merge candidate CSV, rewrite actions. Idempotent."""
    cfg = load_cosp_config()
    cong = int(congress if congress is not None else cfg.get("congress") or 119)
    page_size = int(cfg.get("page_size") or 250)
    members = _member_meta_from_votes_and_config(cfg)
    if not members:
        raise CandidatesError("no VA members found (votes.csv empty and no extra_members)")

    bills: dict[str, BillRef] = {}
    incoming_actions: list[dict[str, str]] = []

    if from_raw:
        for bio, meta in members.items():
            for kind in ("sponsored", "cosponsored"):
                refs = _parse_cached(cong, bio, kind)
                for ref in refs:
                    bills.setdefault(ref.bill_id, ref)
                    incoming_actions.append(
                        {
                            **meta,
                            "bill_id": ref.bill_id,
                            "role": "sponsor" if kind == "sponsored" else "cosponsor",
                        }
                    )
    elif api_key:
        with create_client(headers={"X-Api-Key": api_key}) as client:
            for bio, meta in members.items():
                for kind in ("sponsored", "cosponsored"):
                    paths = fetch_member_legislation(
                        client,
                        bio,
                        kind,  # type: ignore[arg-type]
                        congress=cong,
                        force=force,
                        page_size=page_size,
                    )
                    refs = parse_member_legislation(paths)
                    for ref in refs:
                        bills.setdefault(ref.bill_id, ref)
                        incoming_actions.append(
                            {
                                **meta,
                                "bill_id": ref.bill_id,
                                "role": "sponsor" if kind == "sponsored" else "cosponsor",
                            }
                        )
    else:
        raise CandidatesError("set CONGRESS_API_KEY or pass --from-raw")

    scoring = load_scoring_config()
    proposed = propose_from_bills(list(bills.values()), scoring=scoring)
    merged_cands = merge_candidates(load_candidates(CANDIDATES_PATH), proposed)
    errors = validate_candidates(merged_cands)
    if errors:
        raise CandidatesError("merge failed validation:\n" + "\n".join(errors[:20]))
    write_candidates(merged_cands)
    merged_actions = merge_actions(load_actions(), incoming_actions)
    write_actions(merged_actions)
    return {
        "members": len(members),
        "bills_seen": len(bills),
        "candidates": len(merged_cands),
        "adjudicated": sum(1 for r in merged_cands if r.adjudicated),
        "actions": len(merged_actions),
        "proposed": len(proposed),
    }
