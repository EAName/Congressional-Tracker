"""Filesystem layout for raw landing zone and warehouse."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _looks_like_repo(path: Path) -> bool:
    return (path / "AGENTS.md").is_file() and (path / "pyproject.toml").is_file()


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """
    Locate the repository root.

    Prefer VACT_REPO_ROOT, then walk from CWD and this file until AGENTS.md +
    pyproject.toml are found. Failure mode: ambient package installs that
    aren't the project tree must set VACT_REPO_ROOT explicitly.
    """
    env = os.environ.get("VACT_REPO_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if not _looks_like_repo(root):
            raise RuntimeError(
                f"VACT_REPO_ROOT={root} does not look like the tracker repo"
            )
        return root

    candidates = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    for start in candidates:
        for parent in [start, *start.parents]:
            if _looks_like_repo(parent):
                return parent

    raise RuntimeError(
        "cannot locate va-congressional-tracker repo root; set VACT_REPO_ROOT"
    )


REPO_ROOT = repo_root()
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
