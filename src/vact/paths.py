"""Filesystem layout for raw landing zone and warehouse."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE_DIR = DATA_DIR / "warehouse"
WAREHOUSE_PATH = WAREHOUSE_DIR / "warehouse.duckdb"
SQL_DIR = REPO_ROOT / "sql"


def raw_path(source: str, year: int | str, identifier: str, ext: str) -> Path:
    """Return `data/raw/{source}/{yyyy}/{identifier}.{ext}` and ensure parents exist."""
    path = RAW_DIR / source / str(year) / f"{identifier}.{ext.lstrip('.')}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
