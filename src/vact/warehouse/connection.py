"""DuckDB connection helpers."""

from __future__ import annotations

from pathlib import Path

import duckdb

from vact.paths import SQL_DIR, WAREHOUSE_DIR, WAREHOUSE_PATH


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (and create parent dirs for) the project warehouse."""
    warehouse = path or WAREHOUSE_PATH
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(warehouse))


def apply_sql_file(conn: duckdb.DuckDBPyConnection, relative_sql: str) -> None:
    """Execute a .sql file under sql/."""
    sql_path = SQL_DIR / relative_sql
    if not sql_path.exists():
        raise FileNotFoundError(sql_path)
    conn.execute(sql_path.read_text(encoding="utf-8"))


def ensure_warehouse_dirs() -> None:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
