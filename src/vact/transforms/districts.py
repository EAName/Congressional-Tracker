"""Virginia congressional district map crosswalk (2021 court-drawn vs 2026 proposed)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from vact.models.legislators import DimDistrictRow, DimLegislatorRow
from vact.paths import REPO_ROOT

DISTRICTS_CONFIG_PATH = REPO_ROOT / "config" / "districts.yaml"

MapVersion = Literal["2021", "2026"]
MAP_VERSIONS: tuple[MapVersion, ...] = ("2021", "2026")

# Four GOP-held seats the proposed 2026 map shifted toward Democrats.
TARGET_DISTRICTS_2026: frozenset[int] = frozenset({1, 2, 5, 6})


@dataclass(frozen=True)
class DistrictSpec:
    district_number: int
    map_version: MapVersion
    incumbent_bioguide: str
    partisan_lean: str
    is_target: bool


def load_district_specs(path: Path | None = None) -> list[DistrictSpec]:
    """Load auditable district specs from config/districts.yaml."""
    cfg_path = path or DISTRICTS_CONFIG_PATH
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    maps = payload.get("maps") or {}
    if set(maps) != {"2021", "2026"}:
        raise ValueError(
            f"districts.yaml must define maps 2021 and 2026; got {sorted(maps)}"
        )

    configured_targets = frozenset(int(x) for x in (payload.get("target_districts_2026") or []))
    if configured_targets != TARGET_DISTRICTS_2026:
        raise ValueError(
            f"target_districts_2026 must equal {sorted(TARGET_DISTRICTS_2026)}; "
            f"got {sorted(configured_targets)}"
        )

    specs: list[DistrictSpec] = []
    for map_version in MAP_VERSIONS:
        districts = maps[map_version].get("districts") or {}
        if set(int(k) for k in districts) != set(range(1, 12)):
            raise ValueError(
                f"map {map_version} must define districts 1-11; "
                f"got {sorted(int(k) for k in districts)}"
            )
        for raw_num, entry in districts.items():
            num = int(raw_num)
            is_target = bool(entry["is_target"])
            if map_version == "2026":
                if is_target != (num in TARGET_DISTRICTS_2026):
                    raise ValueError(
                        f"VA-{num} map 2026 is_target={is_target} disagrees with "
                        f"TARGET_DISTRICTS_2026"
                    )
            elif is_target:
                raise ValueError(f"map 2021 must not mark VA-{num} as target")
            specs.append(
                DistrictSpec(
                    district_number=num,
                    map_version=map_version,
                    incumbent_bioguide=str(entry["incumbent_bioguide"]),
                    partisan_lean=str(entry["partisan_lean"]),
                    is_target=is_target,
                )
            )
    return specs


def build_dim_district_rows(path: Path | None = None) -> list[DimDistrictRow]:
    """Emit dim_district rows for both map versions (22 rows)."""
    return [
        DimDistrictRow(
            district_number=s.district_number,
            map_version=s.map_version,
            incumbent_bioguide=s.incumbent_bioguide,
            partisan_lean=s.partisan_lean,
            is_target=s.is_target,
        )
        for s in load_district_specs(path)
    ]


def map_district_for_legislator(
    *,
    chamber: str,
    district_current: int | None,
    map_version: MapVersion,
) -> int | None:
    """
    Resolve district_2025 / district_2026 for a legislator row.

    Kit rule: district numbering persists across map versions; geography changes.
    Senators have no district. House members keep their district_current number
    under both keys; analytics join dim_district on (number, map_version) for lean.
    """
    if chamber != "House":
        return None
    if district_current is None:
        raise ValueError("House legislator missing district_current")
    if district_current not in range(1, 12):
        raise ValueError(f"invalid VA district_current={district_current}")
    if map_version not in MAP_VERSIONS:
        raise ValueError(f"unknown map_version={map_version!r}")
    return district_current


def attach_map_districts(rows: list[DimLegislatorRow]) -> list[DimLegislatorRow]:
    """Fill district_2025 / district_2026 on dim_legislator rows (numbering persists)."""
    out: list[DimLegislatorRow] = []
    for row in rows:
        data = row.model_dump()
        data["district_2025"] = map_district_for_legislator(
            chamber=row.chamber,
            district_current=row.district_current,
            map_version="2021",
        )
        data["district_2026"] = map_district_for_legislator(
            chamber=row.chamber,
            district_current=row.district_current,
            map_version="2026",
        )
        out.append(DimLegislatorRow.model_validate(data))
    return out


def require_map_version(map_version: str) -> MapVersion:
    """Guard used by future exports: refuse silent map mixing."""
    if map_version not in MAP_VERSIONS:
        raise ValueError(
            f"analytic/export must name map_version in {MAP_VERSIONS}; got {map_version!r}"
        )
    return map_version  # type: ignore[return-value]
