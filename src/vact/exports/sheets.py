"""Google Sheets audit export (gspread service account)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import structlog

from vact.exports.data import (
    SCORECARD_TAGS,
    generated_at_utc,
    list_delegation,
    scorecard_rows,
    target_four,
    vote_detail_audit_rows,
)
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
BATCH_ROW_CAP = 500

TAB_README = "README"
TAB_TARGET = "Target Four"
TAB_FULL = "Full Delegation"
TAB_DETAIL = "Vote Detail"

SCORECARD_HEADER = [
    "Member",
    "Party",
    "Chamber",
    "District",
    "Map version",
    "Partisan lean",
    "Is target",
    *[f"{t} (Y/N)" for t in SCORECARD_TAGS],
]


class SheetsConfigError(RuntimeError):
    """Missing or invalid Sheets env configuration."""


def credentials_path() -> Path:
    raw = os.environ.get("VACT_SHEETS_CREDENTIALS")
    if not raw:
        raise SheetsConfigError(
            "Set VACT_SHEETS_CREDENTIALS to the service-account JSON path."
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise SheetsConfigError(f"VACT_SHEETS_CREDENTIALS file not found: {path}")
    return path


def spreadsheet_id() -> str:
    sid = os.environ.get("VACT_SHEETS_ID")
    if not sid:
        raise SheetsConfigError("Set VACT_SHEETS_ID to the target spreadsheet ID.")
    return sid


def _open_client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        str(credentials_path()), scopes=SHEETS_SCOPE
    )
    return gspread.authorize(creds), creds.service_account_email


def preflight() -> dict[str, str]:
    """
    Authenticate and attempt a read. On failure, print share instructions.
    """
    try:
        client, email = _open_client()
        sid = spreadsheet_id()
        sh = client.open_by_key(sid)
        _ = sh.sheet1.row_values(1)
        return {"status": "ok", "spreadsheet": sh.title, "service_account": email}
    except SheetsConfigError:
        raise
    except Exception as err:  # noqa: BLE001 — surface opaque 403 as actionable copy
        email = "unknown"
        try:
            _, email = _open_client()
        except Exception:  # noqa: BLE001
            pass
        message = (
            f"Sheets preflight failed ({err}).\n"
            f"Share the spreadsheet with this service account as Editor:\n"
            f"  {email}\n"
            "A service account is its own principal and has no access until shared; "
            "an unshared sheet usually presents as an opaque 403."
        )
        raise RuntimeError(message) from err


def _scorecard_matrix(rows: list[dict[str, Any]]) -> list[list[Any]]:
    out = [SCORECARD_HEADER]
    for r in rows:
        out.append(
            [
                r["full_name"],
                r["party"],
                r["chamber"],
                r["district_number"] if r["district_number"] is not None else "Statewide",
                r["map_version"],
                r.get("partisan_lean") or "",
                "YES" if r.get("is_target") else "NO",
                *[r[t] for t in SCORECARD_TAGS],
            ]
        )
    return out


def build_readme_values(*, generated_at: str, corpus_votes: int) -> list[list[Any]]:
    return [
        ["Field", "Value"],
        ["generated_at_utc", generated_at],
        ["corpus_vote_count", corpus_votes],
        ["map_version", "2026 (Target Four / Full Delegation lean columns)"],
        ["purpose", "Audit layer for VA Congressional Tracker — not the primary public surface."],
        [
            "sources",
            "House Clerk EVS (clerk.house.gov); Senate LIS (senate.gov); "
            "unitedstates/congress-legislators",
        ],
        [
            "methodology",
            "Impact tags come from config/impact_rules.yaml (RULE) or human promote "
            "(HUMAN). Unadjudicated LLM tags never appear here.",
        ],
        [
            "procedural_caveat",
            "A NAY on a procedural vote is not evidence of a policy position.",
        ],
        [
            "suppressed_on_site",
            "PROCEDURAL, CLOTURE, NOMINATION, SUSPENSION, MOTION_TO_RECOMMIT "
            "are audit-only and excluded from activist district pages.",
        ],
    ]


def build_tab_payloads(
    conn,
    *,
    generated_at: str | None = None,
) -> dict[str, list[list[Any]]]:
    """Build complete value rectangles in memory (live queries)."""
    from vact.exports.data import corpus_vote_count

    ts = generated_at or generated_at_utc()
    targets = scorecard_rows(conn, target_four(conn, map_version="2026"))
    full = scorecard_rows(conn, list_delegation(conn, map_version="2026"))
    detail_header = [
        "Member",
        "Party",
        "District",
        "Date",
        "Bill",
        "Plain Language Summary",
        "Position",
        "Impact Tags",
        "Source Link",
    ]
    detail = [detail_header] + vote_detail_audit_rows(conn)
    return {
        TAB_README: build_readme_values(
            generated_at=ts, corpus_votes=corpus_vote_count(conn)
        ),
        TAB_TARGET: _scorecard_matrix(targets),
        TAB_FULL: _scorecard_matrix(full),
        TAB_DETAIL: detail,
    }


def _chunk_rows(values: Sequence[Sequence[Any]], size: int = BATCH_ROW_CAP):
    for i in range(0, len(values), size):
        yield i, values[i : i + size]


def _ensure_worksheet(sh, title: str, rows: int, cols: int):
    try:
        ws = sh.worksheet(title)
    except Exception:  # gspread.WorksheetNotFound
        ws = sh.add_worksheet(title=title, rows=max(rows, 10), cols=max(cols, 10))
    return ws


def write_tab(ws, values: list[list[Any]]) -> None:
    """
    Write pattern: push the rectangle, then clear only rows beyond the new extent.
    Never clear before writing.
    """
    if not values:
        return
    ncols = max(len(r) for r in values)
    # Pad ragged rows
    rectangle = [list(r) + [""] * (ncols - len(r)) for r in values]

    for start, chunk in _chunk_rows(rectangle):
        start_row = start + 1
        end_row = start + len(chunk)
        end_col_letter = _col_letter(ncols)
        range_name = f"A{start_row}:{end_col_letter}{end_row}"
        ws.update(range_name, chunk, value_input_option="RAW")

    # Clear stale rows below the new extent only.
    if ws.row_count > len(rectangle):
        clear_start = len(rectangle) + 1
        ws.batch_clear([f"A{clear_start}:{_col_letter(ncols)}{ws.row_count}"])


def _col_letter(n: int) -> str:
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def push(*, warehouse_path: Path | None = None) -> dict[str, int]:
    """Push all four audit tabs. Requires successful preflight credentials."""
    client, email = _open_client()
    sid = spreadsheet_id()
    sh = client.open_by_key(sid)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        payloads = build_tab_payloads(conn)
    finally:
        conn.close()

    counts: dict[str, int] = {}
    for title, values in payloads.items():
        ncols = max((len(r) for r in values), default=1)
        ws = _ensure_worksheet(sh, title, rows=len(values) + 5, cols=ncols)
        write_tab(ws, values)
        counts[title] = len(values)
        logger.info("sheets_tab_written", tab=title, rows=len(values), as_email=email)

    # Freeze header + filter on Vote Detail when possible.
    try:
        detail = sh.worksheet(TAB_DETAIL)
        detail.freeze(rows=1)
        # Filter view / basic filter: sheet-level filter via gspread if available.
        body = {
            "requests": [
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": detail.id,
                                "startRowIndex": 0,
                                "startColumnIndex": 0,
                                "endColumnIndex": len(payloads[TAB_DETAIL][0]),
                            }
                        }
                    }
                }
            ]
        }
        sh.batch_update(body)
    except Exception as err:  # noqa: BLE001 — freeze/filter is best-effort
        logger.warning("sheets_detail_filter_skipped", error=str(err))

    return counts
