"""Symmetry audit and excluded-votes tests (Prompt 17)."""

from __future__ import annotations

from pathlib import Path

from vact.analysis.excluded_votes import build_excluded_rows, write_excluded_csv
from vact.analysis.symmetry_audit import build_symmetry_audit, coded_blind_audit
from vact.analysis.votes import VoteRow
from tests.test_scoring import seed_scoring_warehouse
from vact.warehouse.connection import connect, ensure_schema


def _vote_row(
    *,
    bio: str = "A0000001",
    party: str = "Democrat",
    rollcall: str = "h-119-1-1",
    theme: str = "FEDERAL_CONTRACTING",
    axis: str = "advance",
    cast: str = "yea",
    blind: bool = False,
) -> VoteRow:
    return VoteRow.model_validate(
        {
            "member_bioguide_id": bio,
            "member_name": "Ann Alpha",
            "district": "1",
            "party": party,
            "congress": 119,
            "chamber": "House",
            "rollcall_id": rollcall,
            "rollcall_date": "2025-03-01",
            "bill_id": "",
            "theme": theme,
            "axis_direction": axis,
            "vote_cast": cast,
            "contested": "true",
            "adjudication_note": "",
            "adjudicator": "HUMAN",
            "adjudication_date": "2025-03-02",
            "source_url": "http://clerk/h-119-1-1",
            "plain_language_summary": "",
            "coded_blind": blind,
        }
    )


def test_excluded_rows_from_fixture(tmp_path: Path) -> None:
    db = tmp_path / "wh.duckdb"
    seed_scoring_warehouse(db)
    conn = connect(db)
    ensure_schema(conn)
    rows = build_excluded_rows(conn)
    conn.close()
    reasons = {r["reason_code"] for r in rows}
    assert "PROCEDURAL_CATEGORY" in reasons
    assert reasons & {"UNADJUDICATED_DIRECTION", "NO_IMPACT_TAG"}
    path = write_excluded_csv(rows, tmp_path / "excluded.csv")
    assert path.is_file()


def test_coded_blind_audit_share() -> None:
    rows = [
        _vote_row(bio="A0000001", party="Democrat", blind=True),
        _vote_row(bio="B0000002", party="Democrat", blind=True),
        _vote_row(bio="C0000001", party="Republican", rollcall="h-119-1-2", blind=False),
        _vote_row(bio="C0000002", party="Republican", rollcall="h-119-1-2", blind=False),
    ]
    audit = coded_blind_audit(rows)
    assert audit["n_units"] == 2
    assert audit["false_count"] == 1
    assert audit["false_share_pp"] == 50.0


def test_symmetry_audit_flags_structure() -> None:
    vote_rows = [
        _vote_row(bio="A0000001", party="Democrat", cast="yea"),
        _vote_row(bio="B0000002", party="Democrat", cast="yea"),
        _vote_row(bio="R0000001", party="Republican", cast="nay"),
    ]
    scores = [
        {
            "party": "Democrat",
            "n": 5,
            "n_contested": 5,
            "cred_lo": -0.2,
            "cred_hi": 0.4,
        },
        {
            "party": "Republican",
            "n": 5,
            "n_contested": 5,
            "cred_lo": -0.1,
            "cred_hi": 0.5,
        },
    ]
    excluded = [
        {
            "vote_id": "h-119-1-9",
            "reason_code": "PROCEDURAL_CATEGORY",
            "sponsor_party": "Democrat",
        },
        {
            "vote_id": "h-119-1-8",
            "reason_code": "UNADJUDICATED_DIRECTION",
            "sponsor_party": "Republican",
        },
    ]
    audit = build_symmetry_audit(vote_rows, scores, excluded=excluded)
    assert "flags" in audit
    assert "caucus_advancing_by_theme" in audit
    assert audit["coded_blind"]["n_units"] >= 1
