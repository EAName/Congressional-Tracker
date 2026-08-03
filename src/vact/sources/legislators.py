"""Fetch and parse unitedstates/congress-legislators YAML files.

No transformation or warehouse logic lives here. `fetch()` writes unmodified
bytes to disk; `parse()` reads only from disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import structlog
import yaml

from vact.http_client import create_client, get_with_retry
from vact.models.legislators import DistrictOfficesRecord, LegislatorRecord
from vact.paths import raw_path

logger = structlog.get_logger(__name__)

SOURCE = "congress_legislators"
RAW_BASE = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
)

LegislatorFile = Literal[
    "legislators-current",
    "legislators-historical",
    "legislators-district-offices",
]

LEGISLATOR_FILES: tuple[LegislatorFile, ...] = (
    "legislators-current",
    "legislators-historical",
    "legislators-district-offices",
)


def _landing_year(as_of: datetime | None = None) -> int:
    when = as_of or datetime.now(UTC)
    return when.year


def fetch(
    filename: LegislatorFile,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
    as_of: datetime | None = None,
) -> Path:
    """
    Download one YAML file into `data/raw/congress_legislators/{yyyy}/`.

    If the landing file already exists and is non-empty, skip the network call
    unless `force=True`. Returns the path to the raw file.
    """
    year = _landing_year(as_of)
    dest = raw_path(SOURCE, year, filename, "yaml")

    if dest.exists() and dest.stat().st_size > 0 and not force:
        logger.info(
            "legislators_fetch_cache_hit",
            filename=filename,
            path=str(dest),
        )
        return dest

    url = f"{RAW_BASE}/{filename}.yaml"
    owns_client = client is None
    http = client or create_client()
    try:
        response = get_with_retry(http, url)
        response.raise_for_status()
        dest.write_bytes(response.content)
        logger.info(
            "legislators_fetch_wrote",
            filename=filename,
            path=str(dest),
            status_code=response.status_code,
            bytes=len(response.content),
        )
    finally:
        if owns_client:
            http.close()

    return dest


def fetch_all(
    *,
    client: httpx.Client | None = None,
    force: bool = False,
) -> dict[LegislatorFile, Path]:
    """Fetch all three required congress-legislators files."""
    owns_client = client is None
    http = client or create_client()
    try:
        return {
            name: fetch(name, client=http, force=force) for name in LEGISLATOR_FILES
        }
    finally:
        if owns_client:
            http.close()


def parse(path: Path) -> list[LegislatorRecord] | list[DistrictOfficesRecord]:
    """Parse a raw YAML file from disk into Pydantic records."""
    if not path.exists():
        raise FileNotFoundError(f"raw legislator payload missing: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a YAML list in {path}, got {type(payload)!r}")

    stem = path.stem
    if stem == "legislators-district-offices":
        return [DistrictOfficesRecord.model_validate(row) for row in payload]

    if stem in {"legislators-current", "legislators-historical"}:
        return [LegislatorRecord.model_validate(row) for row in payload]

    raise ValueError(f"unsupported legislator payload: {path.name}")


def parse_legislators(path: Path) -> list[LegislatorRecord]:
    """Parse current or historical legislators YAML."""
    records = parse(path)
    if not records:
        return []
    if not isinstance(records[0], LegislatorRecord):
        raise TypeError(f"expected LegislatorRecord list from {path}")
    return records  # type: ignore[return-value]


def parse_district_offices(path: Path) -> list[DistrictOfficesRecord]:
    """Parse district offices YAML."""
    records = parse(path)
    if not records:
        return []
    if not isinstance(records[0], DistrictOfficesRecord):
        raise TypeError(f"expected DistrictOfficesRecord list from {path}")
    return records  # type: ignore[return-value]
