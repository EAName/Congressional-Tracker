"""Tests for gap run grouping and coverage reporting."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from vact.pipeline.backfill import contiguous_runs, write_coverage_report
from vact.warehouse.connection import connect, ensure_schema


def test_contiguous_runs() -> None:
    assert contiguous_runs([]) == []
    assert contiguous_runs([3]) == [(3, 3)]
    assert contiguous_runs([1, 2, 3, 5, 8, 9]) == [(1, 3), (5, 5), (8, 9)]


def test_coverage_report_empty_warehouse(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "w.duckdb"
    conn = connect(db)
    ensure_schema(conn)
    conn.close()

    import vact.pipeline.backfill as bf

    monkeypatch.setattr(bf.house, "discover", lambda year, force=False: set())
    monkeypatch.setattr(
        bf.senate, "discover", lambda congress, session, force=False: set()
    )

    out = write_coverage_report(
        warehouse_path=db, output_path=tmp_path / "coverage.md"
    )
    text = out.read_text(encoding="utf-8")
    assert "Coverage report" in text
    assert "not** proof" in text or "**not** proof" in text
    assert "Weekly heatmap" in text
