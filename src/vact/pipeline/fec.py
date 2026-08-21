"""FEC snapshot pipeline: dated, append-only derived artifacts (Prompt 10).

Writes `data/derived/fec_YYYYMMDD.json`. Same-day re-run is a no-op when the
file already exists (never overwrite prior snapshots).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import structlog

from vact.analysis.races import RaceRegistry, all_fec_candidate_ids, load_races
from vact.http_client import create_client
from vact.paths import DATA_DIR, REPO_ROOT
from vact.sources import fec as fec_source

logger = structlog.get_logger(__name__)

DERIVED_DIR = DATA_DIR / "derived"
DEFAULT_CYCLE = 2026


def snapshot_path(day: date) -> Path:
    return DERIVED_DIR / f"fec_{day.strftime('%Y%m%d')}.json"


def list_snapshots() -> list[Path]:
    if not DERIVED_DIR.is_dir():
        return []
    return sorted(DERIVED_DIR.glob("fec_????????.json"))


def latest_snapshot() -> Path | None:
    paths = list_snapshots()
    return paths[-1] if paths else None


def build_candidate_row(
    *,
    candidate_id: str,
    race_id: str,
    role: str,
    name: str,
    party: str,
    totals_path: Path,
    ie_path: Path,
    cycle: int,
) -> dict[str, Any]:
    totals = fec_source.parse_totals(totals_path, cycle=cycle)
    # Rate-limited DEMO_KEY runs can write empty stubs; fall back to the newest
    # prior raw totals for the same candidate so the snapshot still has dollars.
    if totals.get("receipts") is None:
        prior = sorted(
            (DERIVED_DIR.parent / "raw" / "fec" / str(cycle)).glob(f"{candidate_id}-totals-*.json")
            if (DERIVED_DIR.parent / "raw" / "fec" / str(cycle)).is_dir()
            else [],
            key=lambda p: p.name,
        )
        for path in reversed(prior):
            if path == totals_path:
                continue
            fallback = fec_source.parse_totals(path, cycle=cycle)
            if fallback.get("receipts") is not None:
                totals = fallback
                break
    ie = fec_source.parse_ie(ie_path)
    return {
        "fec_candidate_id": candidate_id,
        "race_id": race_id,
        "role": role,
        "name": name,
        "party": party,
        **totals,
        **ie,
    }


def _candidate_meta(registry: RaceRegistry) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for race in registry.races:
        if race.status.value != "tracked":
            continue
        rows.append(
            {
                "fec_candidate_id": race.incumbent.fec_candidate_id,
                "race_id": race.race_id,
                "role": "incumbent",
                "name": race.incumbent.name,
                "party": race.incumbent.party,
            }
        )
        rows.append(
            {
                "fec_candidate_id": race.challenger.fec_candidate_id,
                "race_id": race.race_id,
                "role": "challenger",
                "name": race.challenger.name,
                "party": race.challenger.party,
            }
        )
    return rows


def snapshot_fec(
    *,
    api_key: str,
    cycle: int = DEFAULT_CYCLE,
    as_of: date | None = None,
    force: bool = False,
    races_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch both candidates in every tracked race into a dated snapshot.

    Same-day re-run is a no-op.
    """
    day = as_of if as_of is not None else date.today()
    dest = snapshot_path(day)
    if dest.is_file() and not force:
        logger.info("fec.snapshot_noop", path=str(dest))
        return {
            "path": dest,
            "noop": True,
            "n_candidates": len(json.loads(dest.read_text(encoding="utf-8")).get("candidates") or []),
        }

    registry = load_races(races_path)
    expected = all_fec_candidate_ids(registry)
    n_tracked = sum(1 for r in registry.races if r.status.value == "tracked")
    if len(expected) != 2 * n_tracked:
        raise ValueError(
            f"expected {2 * n_tracked} tracked FEC IDs ({n_tracked} races x 2), "
            f"got {len(expected)}: {expected}"
        )
    if len(set(expected)) != len(expected):
        raise ValueError(f"duplicate FEC candidate ids across tracked races: {expected}")

    meta = _candidate_meta(registry)
    snapshot_day = day.isoformat()
    candidates: list[dict[str, Any]] = []
    with create_client() as client:
        for row in meta:
            cid = row["fec_candidate_id"]
            totals_path = fec_source.fetch_candidate_totals(
                client,
                cid,
                cycle=cycle,
                api_key=api_key,
                snapshot_day=snapshot_day,
                force=force,
            )
            ie_path = fec_source.fetch_ie_by_candidate(
                client,
                cid,
                cycle=cycle,
                api_key=api_key,
                snapshot_day=snapshot_day,
                force=force,
            )
            candidates.append(
                build_candidate_row(
                    candidate_id=cid,
                    race_id=row["race_id"],
                    role=row["role"],
                    name=row["name"],
                    party=row["party"],
                    totals_path=totals_path,
                    ie_path=ie_path,
                    cycle=cycle,
                )
            )

    got = {c["fec_candidate_id"] for c in candidates}
    missing = set(expected) - got
    if missing:
        raise RuntimeError(f"FEC snapshot missing candidates: {sorted(missing)}")

    payload = {
        "snapshot_date": day.isoformat(),
        "cycle": cycle,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "api.open.fec.gov",
        "n_candidates": len(candidates),
        "candidates": candidates,
    }
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and not force:
        # Race against another writer: still treat as no-op.
        return {"path": dest, "noop": True, "n_candidates": payload["n_candidates"]}
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("fec.snapshot_wrote", path=str(dest), n=len(candidates))
    return {"path": dest, "noop": False, "n_candidates": len(candidates)}
