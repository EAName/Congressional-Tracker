"""Tests for the versioned votes.csv adjudication layer (Prompt 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vact.analysis.deviations import (
    compute_party_deviations,
    compute_party_deviations_from_votes,
)
from vact.analysis.scoring import build_scores_frame, frame_from_vote_rows, load_scoring_config
from vact.analysis.votes import (
    VoteRow,
    VotesValidationError,
    diff_vote_rows,
    validate_vote_rows,
    validate_votes_csv,
    vote_rows_from_warehouse,
    write_votes_csv,
)
from tests.test_deviations import seed_caucus_warehouse
from tests.test_scoring import seed_scoring_warehouse
from vact.paths import REPO_ROOT, WAREHOUSE_PATH
from vact.warehouse.connection import connect

IDENTITY_KEYS = (
    "bioguide_id",
    "impact_tag",
    "n_contested",
    "n_yea",
    "n_nay",
    "n_not_voting",
    "n_present",
    "n_pro",
    "signed_score",
    "wilson_low",
    "wilson_high",
    "sufficient",
    "absence_rate",
)


def _identity(frame: list[dict]) -> list[tuple]:
    return sorted(tuple(r[k] for k in IDENTITY_KEYS) for r in frame)


def _csv_row(**overrides) -> dict:
    base = {
        "member_bioguide_id": "A0000001",
        "member_name": "Ann Alpha",
        "district": "1",
        "party": "D",
        "congress": 119,
        "chamber": "House",
        "rollcall_id": "h-119-1-1",
        "rollcall_date": "2025-03-01",
        "bill_id": "",
        "theme": "FEDERAL_CONTRACTING",
        "axis_direction": "advance",
        "vote_cast": "yea",
        "contested": "true",
        "adjudication_note": "",
        "adjudicator": "HUMAN",
        "adjudication_date": "2025-03-02",
        "source_url": "http://clerk/h-119-1-1",
        "plain_language_summary": "",
    }
    base.update(overrides)
    return base


def test_unique_key_and_enums_round_trip(tmp_path: Path) -> None:
    rows = [
        VoteRow.model_validate(_csv_row()),
        VoteRow.model_validate(_csv_row(member_bioguide_id="B0000002", member_name="Ben Bravo", district="2")),
    ]
    path = tmp_path / "votes.csv"
    write_votes_csv(rows, path)
    loaded = validate_votes_csv(path)
    assert [r.key for r in loaded] == [row.key for row in rows]
    assert loaded[0].vote_cast.value == "yea"
    assert loaded[0].axis_direction.value == "advance"


def test_duplicate_member_rollcall_theme_fails() -> None:
    rows = [
        VoteRow.model_validate(_csv_row()),
        VoteRow.model_validate(_csv_row()),
    ]
    errors = validate_vote_rows(rows)
    assert any("duplicate key" in e for e in errors)


def test_multi_theme_same_rollcall_is_allowed() -> None:
    rows = [
        VoteRow.model_validate(_csv_row()),
        VoteRow.model_validate(_csv_row(theme="HEALTH_COSTS")),
    ]
    assert validate_vote_rows(rows) == []


def test_missing_axis_direction_rejected() -> None:
    with pytest.raises(ValidationError):
        VoteRow.model_validate(_csv_row(axis_direction=""))


def test_missing_source_url_rejected() -> None:
    with pytest.raises(ValidationError):
        VoteRow.model_validate(_csv_row(source_url=""))


def test_vote_cast_enum_rejected() -> None:
    with pytest.raises(ValidationError):
        VoteRow.model_validate(_csv_row(vote_cast="maybe"))


def test_party_inconsistent_across_rows() -> None:
    rows = [
        VoteRow.model_validate(_csv_row(party="D")),
        VoteRow.model_validate(_csv_row(rollcall_id="h-119-1-2", party="R")),
    ]
    errors = validate_vote_rows(rows)
    assert any("party" in e and "disagrees" in e for e in errors)


def test_contested_flag_must_match_vote_cast() -> None:
    rows = [VoteRow.model_validate(_csv_row(vote_cast="yea", contested="false"))]
    errors = validate_vote_rows(rows)
    assert any("contested" in e for e in errors)


def test_warehouse_csv_scores_match_sql_frame(tmp_path: Path) -> None:
    warehouse = seed_scoring_warehouse(tmp_path / "warehouse.duckdb")
    conn = connect(warehouse)
    try:
        cfg = load_scoring_config()
        sql_frame = build_scores_frame(conn, cfg, map_version="2021")
        csv_rows = vote_rows_from_warehouse(conn, cfg, map_version="2021")
        csv_frame = frame_from_vote_rows(csv_rows, cfg, map_version="2021")
    finally:
        conn.close()
    assert _identity(csv_frame) == _identity(sql_frame)
    assert {r.rollcall_id for r in csv_rows} == {
        "h-119-1-1",
        "h-119-1-2",
        "h-119-1-3",
        "h-119-1-4",
        "h-119-1-5",
    }


def test_csv_round_trip_preserves_absence_and_n_pro(tmp_path: Path) -> None:
    warehouse = seed_scoring_warehouse(tmp_path / "warehouse.duckdb")
    conn = connect(warehouse)
    try:
        cfg = load_scoring_config()
        rows = vote_rows_from_warehouse(conn, cfg, map_version="2021")
        sql_frame = build_scores_frame(conn, cfg, map_version="2021")
    finally:
        conn.close()
    path = tmp_path / "votes.csv"
    write_votes_csv(rows, path)
    loaded = validate_votes_csv(path)
    csv_frame = build_scores_frame(config=cfg, map_version="2021", votes_path=path)
    assert _identity(csv_frame) == _identity(sql_frame)
    delta = next(r for r in csv_frame if r["bioguide_id"] == "D0000004")
    assert delta["n_not_voting"] == 1
    assert loaded


def test_deviations_from_csv_match_warehouse(tmp_path: Path) -> None:
    warehouse = seed_caucus_warehouse(tmp_path / "w.duckdb")
    conn = connect(warehouse)
    try:
        cfg = load_scoring_config()
        from_sql = compute_party_deviations(conn, cfg, map_version="2021")
        rows = vote_rows_from_warehouse(conn, cfg, map_version="2021")
    finally:
        conn.close()
    path = tmp_path / "votes.csv"
    write_votes_csv(rows, path)
    from_csv = compute_party_deviations_from_votes(
        validate_votes_csv(path), cfg, map_version="2021"
    )
    assert [d.bioguide_id for d in from_csv] == [d.bioguide_id for d in from_sql]
    assert {v.vote_id for v in from_csv[0].defection_votes} == {
        v.vote_id for v in from_sql[0].defection_votes
    }


def test_diff_detects_added_removed_changed() -> None:
    a = VoteRow.model_validate(_csv_row())
    b = VoteRow.model_validate(_csv_row(member_bioguide_id="B0000002", member_name="Ben"))
    a_flipped = VoteRow.model_validate(_csv_row(axis_direction="oppose", vote_cast="nay"))
    gone = VoteRow.model_validate(_csv_row(rollcall_id="h-119-1-9"))
    diff = diff_vote_rows([a, gone], [b, a_flipped])
    assert len(diff["added"]) == 1
    assert len(diff["removed"]) == 1
    assert len(diff["changed"]) == 1


def test_validate_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_votes_csv(tmp_path / "nope.csv")


def test_validate_bad_csv_raises(tmp_path: Path) -> None:
    path = tmp_path / "votes.csv"
    write_votes_csv([VoteRow.model_validate(_csv_row())], path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text + text.split("\n", 1)[1], encoding="utf-8")  # duplicate data row
    with pytest.raises(VotesValidationError, match="duplicate"):
        validate_votes_csv(path)


@pytest.mark.skipif(not WAREHOUSE_PATH.is_file(), reason="local warehouse not present")
def test_live_warehouse_csv_matches_sql_frame() -> None:
    conn = connect(WAREHOUSE_PATH)
    try:
        cfg = load_scoring_config()
        sql_frame = build_scores_frame(conn, cfg, map_version="2021")
        rows = vote_rows_from_warehouse(conn, cfg, map_version="2021")
    finally:
        conn.close()
    csv_frame = frame_from_vote_rows(rows, cfg, map_version="2021")
    assert _identity(csv_frame) == _identity(sql_frame)


@pytest.mark.skipif(
    not (REPO_ROOT / "data" / "votes.csv").is_file()
    or not (REPO_ROOT / "web" / "data" / "scores.json").is_file(),
    reason="committed votes.csv / scores.json not present",
)
def test_committed_votes_csv_matches_web_scores_json() -> None:
    """Published signed scores must match a live recompute from votes.csv."""
    cfg = load_scoring_config()
    frame = frame_from_vote_rows(
        validate_votes_csv(REPO_ROOT / "data" / "votes.csv"),
        cfg,
        map_version="2021",
    )
    published = json.loads((REPO_ROOT / "web" / "data" / "scores.json").read_text(encoding="utf-8"))
    csv_map = {
        (r["bioguide_id"], r["impact_tag"]): (
            r["signed_score"],
            r["wilson_low"],
            r["wilson_high"],
            r["n_contested"],
        )
        for r in frame
        if r["signed_score"] is not None
    }
    json_map = {
        (r["bioguide_id"], r["theme"]): (
            r["signed_score"],
            r["wilson_low"],
            r["wilson_high"],
            r["n_contested"],
        )
        for r in published
    }
    assert csv_map == json_map
