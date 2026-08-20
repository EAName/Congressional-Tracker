"""Race registry and FEC snapshot tests (Prompt 10)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from vact.analysis.races import (
    RACES_PATH,
    RacesValidationError,
    days_until_election,
    load_races,
    races_for_web,
    validate_races,
)
from vact.pipeline.fec import snapshot_fec, snapshot_path
from vact.sources import fec as fec_source


def test_committed_registry_validates() -> None:
    reg = validate_races(RACES_PATH)
    assert {r.race_id for r in reg.races if r.status.value == "tracked"} == {
        "va-01",
        "va-02",
        "va-05",
    }
    assert all(r.election_date.isoformat() == "2026-11-03" for r in reg.races)
    fec_ids = []
    for r in reg.races:
        fec_ids.extend([r.incumbent.fec_candidate_id, r.challenger.fec_candidate_id])
    assert len(fec_ids) == 6
    assert len(set(fec_ids)) == 6
    assert reg.races[0].challenger.prior_federal_service is None  # Taylor
    assert reg.races[1].challenger.prior_federal_service is not None  # Luria


def test_tracked_missing_fec_fails(tmp_path: Path) -> None:
    payload = json.loads(RACES_PATH.read_text(encoding="utf-8"))
    payload["races"][0]["challenger"]["fec_candidate_id"] = ""
    path = tmp_path / "races.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RacesValidationError):
        validate_races(path)


def test_days_until_election_is_deterministic() -> None:
    assert days_until_election(date(2026, 11, 3), as_of=date(2026, 8, 19)) == 76
    assert days_until_election(date(2026, 11, 3), as_of=date(2026, 11, 3)) == 0
    assert days_until_election(date(2026, 11, 3), as_of=date(2026, 11, 4)) == -1


def test_races_for_web_injects_days() -> None:
    out = races_for_web(as_of=date(2026, 8, 19))
    assert out["days_until_election"] == 76
    assert all("days_until_election" in r for r in out["races"])
    assert out["as_of"] == "2026-08-19"


def test_parse_totals_small_dollar_share(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "cycle": 2026,
                        "receipts": 1000.0,
                        "last_cash_on_hand_end_period": 200.0,
                        "individual_contributions": 400.0,
                        "individual_unitemized_contributions": 100.0,
                        "coverage_end_date": "2026-07-15T00:00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    parsed = fec_source.parse_totals(path, cycle=2026)
    assert parsed["receipts"] == 1000.0
    assert parsed["small_dollar_share"] == 0.25


def test_parse_ie_support_oppose(tmp_path: Path) -> None:
    path = tmp_path / "ie.json"
    path.write_text(
        json.dumps(
            {
                "results": [
                    {"support_oppose_indicator": "S", "total": 10.0},
                    {"support_oppose_indicator": "O", "total": 5.5},
                    {"support_oppose_indicator": "S", "total": 2.0},
                ]
            }
        ),
        encoding="utf-8",
    )
    ie = fec_source.parse_ie(path)
    assert ie["independent_expenditures_support"] == 12.0
    assert ie["independent_expenditures_oppose"] == 5.5


def test_snapshot_same_day_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    day = date(2026, 8, 19)
    dest = tmp_path / f"fec_{day.strftime('%Y%m%d')}.json"
    dest.write_text(
        json.dumps({"candidates": [{"fec_candidate_id": f"H{i}"} for i in range(6)]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("vact.pipeline.fec.DERIVED_DIR", tmp_path)
    monkeypatch.setattr("vact.pipeline.fec.snapshot_path", lambda d: tmp_path / f"fec_{d.strftime('%Y%m%d')}.json")

    def boom(*_a, **_k):
        raise AssertionError("network must not run on same-day no-op")

    monkeypatch.setattr("vact.pipeline.fec.create_client", boom)
    result = snapshot_fec(api_key="unused", as_of=day)
    assert result["noop"] is True
    assert result["path"] == dest
