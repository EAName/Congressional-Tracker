"""Google Sheets product export (gspread; service account or OAuth).

Dashboard is the primary surface: live stats, embedded charts, scorecards.
Legacy stub tabs from the hand-built v1 workbook are renamed and hidden.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import structlog

from vact.exports.data import (
    SITE_SCORECARD_TAGS,
    corpus_vote_count,
    display_category,
    generated_at_utc,
    impact_tag_mix,
    list_delegation,
    publication_ready_count,
    scorecard_rows,
    tagged_vote_count,
    target_four,
    vote_category_mix,
    vote_detail_audit_rows,
)
from vact.paths import REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
BATCH_ROW_CAP = 500

TAB_DASHBOARD = "Dashboard"
TAB_README = "README"
TAB_TARGET = "Target Four"
TAB_FULL = "Full Delegation"
TAB_DETAIL = "Vote Detail"

# Hand-built v1 stubs. Deleted on every push so the share link is not the
# Vacant-VA-11 roster.
LEGACY_TAB_TITLES = (
    "Legislators",
    "Votes",
    "Small Business Votes",
    "Sheet5",
    "Vote Positions",
)
LEGACY_PREFIX = "_Archive · "

WORKBOOK_TITLE = "VA Congressional Vote Tracker"

# Match the press site: tags with live density (no empty TAX_BURDEN column).
SHEETS_SCORECARD_TAGS = SITE_SCORECARD_TAGS

DEFAULT_OAUTH_CLIENT = Path.home() / ".config" / "gspread" / "credentials.json"
DEFAULT_OAUTH_TOKEN = Path.home() / ".config" / "gspread" / "authorized_user.json"
LOCAL_OAUTH_CLIENT = REPO_ROOT / "secrets" / "oauth_client.json"
LOCAL_OAUTH_TOKEN = REPO_ROOT / "secrets" / "authorized_user.json"

SCORECARD_HEADER = [
    "Member",
    "Party",
    "Chamber",
    "District",
    "Map",
    "Lean",
    "Target",
    *[t.replace("_", " ").title() for t in SHEETS_SCORECARD_TAGS],
]


class SheetsConfigError(RuntimeError):
    """Missing or invalid Sheets env configuration."""


def auth_mode() -> str:
    """service_account (default) or oauth."""
    return (os.environ.get("VACT_SHEETS_AUTH") or "service_account").strip().lower()


def credentials_path() -> Path:
    raw = os.environ.get("VACT_SHEETS_CREDENTIALS")
    if not raw:
        raise SheetsConfigError(
            "Set VACT_SHEETS_CREDENTIALS to the service-account JSON path "
            "(or set VACT_SHEETS_AUTH=oauth)."
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise SheetsConfigError(f"VACT_SHEETS_CREDENTIALS file not found: {path}")
    return path


def oauth_client_path() -> Path:
    raw = os.environ.get("VACT_SHEETS_OAUTH_CLIENT")
    if raw:
        path = Path(raw).expanduser().resolve()
    elif LOCAL_OAUTH_CLIENT.is_file():
        path = LOCAL_OAUTH_CLIENT
    else:
        path = DEFAULT_OAUTH_CLIENT
    if not path.is_file():
        raise SheetsConfigError(
            "OAuth client JSON not found.\n"
            f"Expected: {path}\n"
            "Create a Desktop OAuth client in Google Cloud Console, download the JSON, "
            f"and save it to that path (or set VACT_SHEETS_OAUTH_CLIENT)."
        )
    return path


def oauth_token_path() -> Path:
    raw = os.environ.get("VACT_SHEETS_OAUTH_TOKEN")
    if raw:
        path = Path(raw).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    client = Path(os.environ.get("VACT_SHEETS_OAUTH_CLIENT", "")).expanduser() if os.environ.get(
        "VACT_SHEETS_OAUTH_CLIENT"
    ) else (LOCAL_OAUTH_CLIENT if LOCAL_OAUTH_CLIENT.is_file() else DEFAULT_OAUTH_CLIENT)
    if client == LOCAL_OAUTH_CLIENT or str(client).startswith(str(REPO_ROOT / "secrets")):
        LOCAL_OAUTH_TOKEN.parent.mkdir(parents=True, exist_ok=True)
        return LOCAL_OAUTH_TOKEN
    DEFAULT_OAUTH_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OAUTH_TOKEN


def spreadsheet_id() -> str:
    sid = os.environ.get("VACT_SHEETS_ID")
    if not sid:
        return "1fbjfNKB79-Rzq70X9Ixg67aVzxYmv6nxxj-hCVQDyi0"
    return sid


def _open_service_account():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        str(credentials_path()), scopes=SHEETS_SCOPES
    )
    return gspread.authorize(creds), creds.service_account_email


def _load_oauth_client_config(client_path: Path) -> dict:
    import json

    raw = json.loads(client_path.read_text(encoding="utf-8"))
    if "installed" in raw:
        return raw
    if "web" in raw:
        web = dict(raw["web"])
        redirects = list(web.get("redirect_uris") or [])
        for uri in ("http://localhost", "http://localhost:8080/", "http://127.0.0.1"):
            if uri not in redirects:
                redirects.append(uri)
        web["redirect_uris"] = redirects
        return {"installed": web}
    raise SheetsConfigError(
        f"OAuth client JSON must contain 'installed' or 'web'; got keys {sorted(raw)}"
    )


def _open_oauth(*, interactive: bool = True):
    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = oauth_client_path()
    token_path = oauth_token_path()
    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SHEETS_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        if not interactive:
            raise SheetsConfigError(
                f"OAuth token missing/expired at {token_path}. Run: vact sheets auth"
            )
        client_config = _load_oauth_client_config(client_path)
        flow = InstalledAppFlow.from_client_config(client_config, SHEETS_SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("oauth_token_saved", path=str(token_path))
    return gspread.authorize(creds), "oauth-user"


def _open_client(*, interactive: bool = False):
    mode = auth_mode()
    if mode in {"oauth", "user", "browser"}:
        return _open_oauth(interactive=interactive)
    if mode in {"service_account", "sa"}:
        return _open_service_account()
    raise SheetsConfigError(f"Unknown VACT_SHEETS_AUTH={mode!r} (use oauth or service_account)")


def run_oauth_login() -> Path:
    """Interactive browser login; writes authorized_user.json."""
    _open_oauth(interactive=True)
    return oauth_token_path()


def preflight() -> dict[str, str]:
    try:
        client, email = _open_client(interactive=False)
        sid = spreadsheet_id()
        sh = client.open_by_key(sid)
        _ = sh.sheet1.row_values(1)
        return {
            "status": "ok",
            "spreadsheet": sh.title,
            "account": email,
            "auth": auth_mode(),
            "spreadsheet_id": sid,
        }
    except SheetsConfigError:
        raise
    except Exception as err:  # noqa: BLE001
        mode = auth_mode()
        if mode in {"oauth", "user", "browser"}:
            message = (
                f"Sheets preflight failed ({err}).\n"
                "With OAuth, sign in as a Google account that already has Editor access "
                "to the spreadsheet. Re-run: vact sheets auth"
            )
        else:
            email = "unknown"
            try:
                _, email = _open_service_account()
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
                r.get("partisan_lean") or "—",
                "Yes" if r.get("is_target") else "No",
                *[r[t] for t in SHEETS_SCORECARD_TAGS],
            ]
        )
    return out


def build_readme_values(
    *,
    generated_at: str,
    corpus_votes: int,
    tagged: int = 0,
    ready: int = 0,
) -> list[list[Any]]:
    return [
        ["Field", "Value"],
        ["generated_at_utc", generated_at],
        ["corpus_vote_count", corpus_votes],
        ["tagged_vote_count", tagged],
        ["publication_ready_count", ready],
        ["map_version", "2026"],
        ["primary_surface", "Dashboard tab (charts + Target Four + Full Delegation scorecards)"],
        [
            "sources",
            "House Clerk EVS (clerk.house.gov); Senate LIS (senate.gov); "
            "unitedstates/congress-legislators",
        ],
        [
            "methodology",
            "Impact tags from config/impact_rules.yaml (RULE) or human promote (HUMAN). "
            "Unadjudicated LLM tags never appear.",
        ],
        [
            "procedural_caveat",
            "A NAY on a procedural vote is not evidence of a policy position.",
        ],
        [
            "legacy_tabs",
            "Old hand-built Legislators/Votes stubs are deleted on each push.",
        ],
    ]


def build_dashboard_layout(
    conn,
    *,
    generated_at: str | None = None,
) -> tuple[list[list[Any]], dict[str, Any]]:
    """
    Build the Dashboard rectangle plus chart source coordinates (1-based).

    Left side (A–L): title, snapshot, Target Four, Full Delegation.
    Right side (N–R): chart source tables (kept out of the primary read path).
    """
    ts = generated_at or generated_at_utc()
    votes = corpus_vote_count(conn)
    tagged = tagged_vote_count(conn)
    ready = publication_ready_count(conn)
    categories = vote_category_mix(conn)
    tags = impact_tag_mix(conn)
    target_members = scorecard_rows(
        conn, target_four(conn, map_version="2026"), tags=SHEETS_SCORECARD_TAGS
    )
    full_members = scorecard_rows(
        conn, list_delegation(conn, map_version="2026"), tags=SHEETS_SCORECARD_TAGS
    )
    targets = _scorecard_matrix(target_members)
    full = _scorecard_matrix(full_members)

    # Chart sources live in columns N–R (1-based cols 14–18) so the scorecard leads.
    chart_col_cat = 14  # N
    chart_col_tag = 17  # Q
    chart_header_row = 1
    chart_data_start = 2
    n_cat = max(len(categories), 1)
    n_tag = max(len(tags), 1)
    chart_height = max(n_cat, n_tag)
    chart_data_end = chart_data_start + chart_height - 1
    width = max(18, chart_col_tag + 1)

    def blank_row() -> list[Any]:
        return [""] * width

    def pad(row: list[Any]) -> list[Any]:
        return list(row) + [""] * (width - len(row))

    rows: list[list[Any]] = [
        pad(["VA Congressional Vote Tracker"]),
        pad(["Democrats for Virginia · Small Business Caucus"]),
        pad(["Updated (UTC)", ts, "Map", "2026"]),
        pad(
            [
                "Official roll calls",
                votes,
                "Impact-tagged votes",
                tagged,
                "Virginia members",
                13,
            ]
        ),
        pad(
            [
                "Sources",
                "House Clerk · Senate LIS · congress-legislators",
            ]
        ),
        blank_row(),
        pad(
            [
                "TARGET FOUR — proposed 2026 map seats leaning toward Democrats",
            ]
        ),
    ]
    target_start = len(rows) + 1
    for block_row in targets:
        rows.append(pad(block_row))

    rows.append(blank_row())
    rows.append(
        pad(
            [
                "FULL DELEGATION — Yea / Nay on impact-tagged votes",
            ]
        )
    )
    rows.append(
        pad(
            [
                "Green cells lean Yea · red lean Nay · dash = no tagged votes yet in that theme",
            ]
        )
    )
    full_start = len(rows) + 1
    for block_row in full:
        rows.append(pad(block_row))

    # Ensure enough rows for chart source block.
    while len(rows) < chart_data_end:
        rows.append(blank_row())

    # Write chart headers/data into N and Q columns (0-based indexes 13 and 16).
    rows[0][chart_col_cat - 1] = "Vote category"
    rows[0][chart_col_cat] = "Count"
    rows[0][chart_col_tag - 1] = "Impact tag"
    rows[0][chart_col_tag] = "Count"
    for i in range(chart_height):
        r_idx = chart_data_start - 1 + i
        while len(rows) <= r_idx:
            rows.append(blank_row())
        cat = categories[i] if i < len(categories) else {"label": "", "count": ""}
        tag = tags[i] if i < len(tags) else {"label": "", "count": ""}
        rows[r_idx][chart_col_cat - 1] = display_category(str(cat["label"])) if cat["label"] else ""
        rows[r_idx][chart_col_cat] = cat["count"]
        rows[r_idx][chart_col_tag - 1] = (
            str(tag["label"]).replace("_", " ").title() if tag["label"] else ""
        )
        rows[r_idx][chart_col_tag] = tag["count"]

    meta = {
        "sheet_title": TAB_DASHBOARD,
        "category_header_row": chart_header_row,
        "category_start_row": chart_data_start,
        "category_end_row": chart_data_end,
        "impact_header_row": chart_header_row,
        "impact_start_row": chart_data_start,
        "impact_end_row": chart_data_end,
        "category_col": chart_col_cat - 1,  # 0-based
        "impact_col": chart_col_tag - 1,
        "n_categories": len(categories),
        "n_tags": len(tags),
        "target_header_row": target_start,
        "target_rows": len(targets),
        "full_header_row": full_start,
        "full_rows": len(full),
        "score_col_start": 7,  # 0-based: first impact tag col
        "score_col_end": 7 + len(SHEETS_SCORECARD_TAGS),
        "ncols": width,
        "generated_at": ts,
        "corpus_votes": votes,
        "tagged": tagged,
        "ready": ready,
    }
    return rows, meta


def build_tab_payloads(
    conn,
    *,
    generated_at: str | None = None,
) -> dict[str, list[list[Any]]]:
    """Build complete value rectangles in memory (live queries)."""
    ts = generated_at or generated_at_utc()
    dashboard, _meta = build_dashboard_layout(conn, generated_at=ts)
    targets = scorecard_rows(
        conn, target_four(conn, map_version="2026"), tags=SHEETS_SCORECARD_TAGS
    )
    full = scorecard_rows(
        conn, list_delegation(conn, map_version="2026"), tags=SHEETS_SCORECARD_TAGS
    )
    votes = corpus_vote_count(conn)
    tagged = tagged_vote_count(conn)
    ready = publication_ready_count(conn)
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
        TAB_DASHBOARD: dashboard,
        TAB_TARGET: _scorecard_matrix(targets),
        TAB_FULL: _scorecard_matrix(full),
        TAB_DETAIL: detail,
        TAB_README: build_readme_values(
            generated_at=ts, corpus_votes=votes, tagged=tagged, ready=ready
        ),
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

    def _cell(v: Any) -> Any:
        if v is None:
            return ""
        if hasattr(v, "isoformat") and not isinstance(v, str):
            return v.isoformat()
        return v

    rectangle = [list(_cell(c) for c in r) + [""] * (ncols - len(r)) for r in values]

    for start, chunk in _chunk_rows(rectangle):
        start_row = start + 1
        end_row = start + len(chunk)
        end_col_letter = _col_letter(ncols)
        range_name = f"A{start_row}:{end_col_letter}{end_row}"
        ws.update(range_name, chunk, value_input_option="RAW")

    # Also clear columns beyond the new width on the written row span (stale Dashboard).
    if ws.col_count > ncols:
        clear_cols = f"{_col_letter(ncols + 1)}1:{_col_letter(ws.col_count)}{len(rectangle)}"
        ws.batch_clear([clear_cols])

    if ws.row_count > len(rectangle):
        clear_start = len(rectangle) + 1
        ws.batch_clear([f"A{clear_start}:{_col_letter(max(ncols, ws.col_count))}{ws.row_count}"])


def _col_letter(n: int) -> str:
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _purge_legacy_tabs(sh) -> list[str]:
    """
    Delete hand-built v1 stubs (and prior _Archive · copies) so the share link
    cannot land on Vacant-VA-11 roster content.
    """
    purged: list[str] = []
    # Refresh worksheet list each delete; gspread ids stay valid.
    for ws in list(sh.worksheets()):
        title = ws.title
        is_legacy = title in LEGACY_TAB_TITLES or title.startswith(LEGACY_PREFIX)
        if not is_legacy:
            continue
        if len(sh.worksheets()) <= 1:
            logger.warning("sheets_purge_skipped_last_sheet", title=title)
            break
        sh.del_worksheet(ws)
        purged.append(title)
        logger.info("sheets_legacy_deleted", tab=title)
    return purged


def _set_workbook_title(sh, title: str = WORKBOOK_TITLE) -> None:
    sh.batch_update(
        {
            "requests": [
                {
                    "updateSpreadsheetProperties": {
                        "properties": {"title": title},
                        "fields": "title",
                    }
                }
            ]
        }
    )


def _move_sheet_to_front(sh, ws) -> None:
    sh.batch_update(
        {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": ws.id, "index": 0, "hidden": False},
                        "fields": "index,hidden",
                    }
                }
            ]
        }
    )


def _delete_embedded_charts(sh, sheet_id: int) -> None:
    meta = sh.fetch_sheet_metadata()
    charts = []
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties") or {}
        if props.get("sheetId") != sheet_id:
            continue
        charts = sheet.get("charts") or []
        break
    if not charts:
        return
    sh.batch_update(
        {
            "requests": [
                {"deleteEmbeddedObject": {"objectId": c["chartId"]}} for c in charts
            ]
        }
    )


def _add_dashboard_charts(sh, ws, meta: dict[str, Any]) -> None:
    """Replace Dashboard embedded charts (pie categories + bar impact tags)."""
    sheet_id = ws.id
    _delete_embedded_charts(sh, sheet_id)

    header_idx = meta["category_header_row"] - 1
    cat_end_excl = meta["category_end_row"]
    impact_header_idx = meta["impact_header_row"] - 1
    impact_end_excl = meta["impact_end_row"]
    cat_col = int(meta["category_col"])
    tag_col = int(meta["impact_col"])

    requests = [
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Roll-call mix",
                        "pieChart": {
                            "legendPosition": "RIGHT_LEGEND",
                            "domain": {
                                "sourceRange": {
                                    "sources": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": header_idx,
                                            "endRowIndex": cat_end_excl,
                                            "startColumnIndex": cat_col,
                                            "endColumnIndex": cat_col + 1,
                                        }
                                    ]
                                }
                            },
                            "series": {
                                "sourceRange": {
                                    "sources": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": header_idx,
                                            "endRowIndex": cat_end_excl,
                                            "startColumnIndex": cat_col + 1,
                                            "endColumnIndex": cat_col + 2,
                                        }
                                    ]
                                }
                            },
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": sheet_id,
                                "rowIndex": 0,
                                "columnIndex": 8,
                            },
                            "widthPixels": 380,
                            "heightPixels": 250,
                        }
                    },
                }
            }
        },
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Small-business impact themes",
                        "basicChart": {
                            "chartType": "COLUMN",
                            "legendPosition": "NO_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "Theme"},
                                {"position": "LEFT_AXIS", "title": "Votes"},
                            ],
                            "domains": [
                                {
                                    "domain": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": sheet_id,
                                                    "startRowIndex": impact_header_idx,
                                                    "endRowIndex": impact_end_excl,
                                                    "startColumnIndex": tag_col,
                                                    "endColumnIndex": tag_col + 1,
                                                }
                                            ]
                                        }
                                    }
                                }
                            ],
                            "series": [
                                {
                                    "series": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": sheet_id,
                                                    "startRowIndex": impact_header_idx,
                                                    "endRowIndex": impact_end_excl,
                                                    "startColumnIndex": tag_col + 1,
                                                    "endColumnIndex": tag_col + 2,
                                                }
                                            ]
                                        }
                                    },
                                    "targetAxis": "LEFT_AXIS",
                                }
                            ],
                            "headerCount": 1,
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": sheet_id,
                                "rowIndex": 0,
                                "columnIndex": 11,
                            },
                            "widthPixels": 380,
                            "heightPixels": 250,
                        }
                    },
                }
            }
        },
    ]
    sh.batch_update({"requests": requests})
    logger.info(
        "sheets_dashboard_charts",
        categories=meta["n_categories"],
        tags=meta["n_tags"],
    )


def _score_conditional_rules(
    sheet_id: int,
    *,
    start_row: int,
    end_row: int,
    start_col: int,
    end_col: int,
) -> list[dict[str, Any]]:
    """Color Yea/Nay text cells by majority (custom formulas, 1-based A1 via R1C1)."""
    # Sheets custom formulas are evaluated per cell; relative refs from top-left.
    # start_row/end_row/start_col/end_col are 0-based indices for GridRange.
    return [
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [
                                {
                                    "userEnteredValue": (
                                        '=AND(ISNUMBER(VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN()'
                                        ',FALSE),"^(\\d+)"))),'
                                        'ISNUMBER(VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN()'
                                        ',FALSE),"/ (\\d+)"))),'
                                        'VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN(),FALSE),"^(\\d+)"))'
                                        '>VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN(),FALSE),"/ (\\d+)")))'
                                    )
                                }
                            ],
                        },
                        "format": {
                            "backgroundColor": {"red": 0.85, "green": 0.94, "blue": 0.89},
                            "textFormat": {
                                "foregroundColor": {"red": 0.11, "green": 0.42, "blue": 0.28},
                                "bold": True,
                            },
                        },
                    },
                },
                "index": 0,
            }
        },
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [
                                {
                                    "userEnteredValue": (
                                        '=AND(ISNUMBER(VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN()'
                                        ',FALSE),"^(\\d+)"))),'
                                        'ISNUMBER(VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN()'
                                        ',FALSE),"/ (\\d+)"))),'
                                        'VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN(),FALSE),"^(\\d+)"))'
                                        '<VALUE(REGEXEXTRACT(INDIRECT("R"&ROW()&"C"&COLUMN(),FALSE),"/ (\\d+)")))'
                                    )
                                }
                            ],
                        },
                        "format": {
                            "backgroundColor": {"red": 0.95, "green": 0.84, "blue": 0.87},
                            "textFormat": {
                                "foregroundColor": {"red": 0.60, "green": 0.18, "blue": 0.27},
                                "bold": True,
                            },
                        },
                    },
                },
                "index": 1,
            }
        },
    ]


def _format_workbook(sh, dash_meta: dict[str, Any]) -> None:
    """Bold titles, freeze headers, column widths, conditional score colors."""
    dash = sh.worksheet(TAB_DASHBOARD)
    target = sh.worksheet(TAB_TARGET)
    full = sh.worksheet(TAB_FULL)
    detail = sh.worksheet(TAB_DETAIL)

    # Drop previous conditional rules so each push is deterministic.
    del_reqs: list[dict[str, Any]] = []
    meta = sh.fetch_sheet_metadata()
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties") or {}
        if props.get("title") not in {TAB_DASHBOARD, TAB_TARGET, TAB_FULL, TAB_DETAIL}:
            continue
        for _ in sheet.get("conditionalFormats") or []:
            del_reqs.append(
                {
                    "deleteConditionalFormatRule": {
                        "sheetId": props["sheetId"],
                        "index": 0,
                    }
                }
            )
    if del_reqs:
        sh.batch_update({"requests": del_reqs})

    navy = {"red": 0.06, "green": 0.18, "blue": 0.32}
    band = {"red": 0.93, "green": 0.95, "blue": 0.97}
    sc0 = int(dash_meta["score_col_start"])
    sc1 = int(dash_meta["score_col_end"])
    requests: list[dict[str, Any]] = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": dash.id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 7,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 18,
                            "bold": True,
                            "foregroundColor": navy,
                        }
                    }
                },
                "fields": "userEnteredFormat.textFormat",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": dash.id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 7,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 11,
                            "italic": True,
                            "foregroundColor": {
                                "red": 0.29,
                                "green": 0.36,
                                "blue": 0.44,
                            },
                        }
                    }
                },
                "fields": "userEnteredFormat.textFormat",
            }
        },
    ]

    # Section title rows (1-based) sit one above Target header and two above Full header.
    for title_row in (
        dash_meta["target_header_row"] - 1,
        dash_meta["full_header_row"] - 2,
    ):
        if title_row < 1:
            continue
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": dash.id,
                        "startRowIndex": title_row - 1,
                        "endRowIndex": title_row,
                        "startColumnIndex": 0,
                        "endColumnIndex": 7,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {
                                "bold": True,
                                "fontSize": 12,
                                "foregroundColor": navy,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.textFormat",
                }
            }
        )

    # Scorecard header rows on Dashboard + dedicated tabs.
    for sheet_id, row_1based in (
        (dash.id, dash_meta["target_header_row"]),
        (dash.id, dash_meta["full_header_row"]),
    ):
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_1based - 1,
                        "endRowIndex": row_1based,
                        "startColumnIndex": 0,
                        "endColumnIndex": sc1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True, "foregroundColor": navy},
                            "backgroundColor": band,
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            }
        )

    for ws in (target, full, detail):
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": ws.id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            }
        )
        end_col = len(SCORECARD_HEADER) if ws in (target, full) else 9
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": end_col,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True, "foregroundColor": navy},
                            "backgroundColor": band,
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            }
        )

    # Conditional score colors.
    requests.extend(
        _score_conditional_rules(
            dash.id,
            start_row=dash_meta["target_header_row"],
            end_row=dash_meta["target_header_row"] + dash_meta["target_rows"] - 1,
            start_col=sc0,
            end_col=sc1,
        )
    )
    requests.extend(
        _score_conditional_rules(
            dash.id,
            start_row=dash_meta["full_header_row"],
            end_row=dash_meta["full_header_row"] + dash_meta["full_rows"] - 1,
            start_col=sc0,
            end_col=sc1,
        )
    )
    t_vals = target.get_all_values()
    f_vals = full.get_all_values()
    if len(t_vals) > 1:
        requests.extend(
            _score_conditional_rules(
                target.id,
                start_row=1,
                end_row=len(t_vals),
                start_col=sc0,
                end_col=sc1,
            )
        )
    if len(f_vals) > 1:
        requests.extend(
            _score_conditional_rules(
                full.id,
                start_row=1,
                end_row=len(f_vals),
                start_col=sc0,
                end_col=sc1,
            )
        )

    detail_n = max(2, len(detail.get_all_values()))
    for value, bg, fg in (
        (
            "YEA",
            {"red": 0.85, "green": 0.94, "blue": 0.89},
            {"red": 0.11, "green": 0.42, "blue": 0.28},
        ),
        (
            "NAY",
            {"red": 0.95, "green": 0.84, "blue": 0.87},
            {"red": 0.60, "green": 0.18, "blue": 0.27},
        ),
    ):
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [
                            {
                                "sheetId": detail.id,
                                "startRowIndex": 1,
                                "endRowIndex": detail_n,
                                "startColumnIndex": 6,
                                "endColumnIndex": 7,
                            }
                        ],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": value}],
                            },
                            "format": {
                                "backgroundColor": bg,
                                "textFormat": {
                                    "foregroundColor": fg,
                                    "bold": True,
                                },
                            },
                        },
                    },
                    "index": 0 if value == "YEA" else 1,
                }
            }
        )

    for ws, widths in (
        (dash, [220, 120, 90, 70, 55, 80, 65, 110, 110, 110, 110, 120]),
        (target, [200, 110, 80, 70, 50, 80, 60, 110, 110, 110, 110, 120]),
        (full, [200, 110, 80, 70, 50, 80, 60, 110, 110, 110, 110, 120]),
        (detail, [180, 90, 70, 100, 110, 280, 80, 160, 280]),
    ):
        for i, px in enumerate(widths):
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "COLUMNS",
                            "startIndex": i,
                            "endIndex": i + 1,
                        },
                        "properties": {"pixelSize": px},
                        "fields": "pixelSize",
                    }
                }
            )

    for i in range(0, len(requests), 40):
        sh.batch_update({"requests": requests[i : i + 40]})
    logger.info("sheets_formatted", requests=len(requests))



def push(*, warehouse_path: Path | None = None) -> dict[str, int]:
    """
    Rebuild the product workbook: Dashboard first with charts, live scorecard tabs,
    archive of v1 stubs.
    """
    client, email = _open_client(interactive=False)
    sid = spreadsheet_id()
    sh = client.open_by_key(sid)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        payloads = build_tab_payloads(conn)
        dashboard_values, dash_meta = build_dashboard_layout(
            conn, generated_at=payloads[TAB_README][1][1]
        )
        payloads[TAB_DASHBOARD] = dashboard_values
    finally:
        conn.close()

    # Remove stubs before writing so product tabs are the only visible sheets.
    purged = _purge_legacy_tabs(sh)
    try:
        _set_workbook_title(sh)
    except Exception as err:  # noqa: BLE001
        logger.warning("sheets_title_skip", error=str(err))

    counts: dict[str, int] = {}
    # Write Dashboard first, then supporting tabs.
    order = [TAB_DASHBOARD, TAB_TARGET, TAB_FULL, TAB_DETAIL, TAB_README]
    for title in order:
        values = payloads[title]
        ncols = max((len(r) for r in values), default=1)
        # Dashboard needs width for chart anchors past column L.
        min_cols = 18 if title == TAB_DASHBOARD else ncols
        ws = _ensure_worksheet(
            sh, title, rows=len(values) + 5, cols=max(ncols, min_cols)
        )
        write_tab(ws, values)
        counts[title] = len(values)
        logger.info("sheets_tab_written", tab=title, rows=len(values), as_email=email)

    dash = sh.worksheet(TAB_DASHBOARD)
    _move_sheet_to_front(sh, dash)
    try:
        _add_dashboard_charts(sh, dash, dash_meta)
    except Exception as err:  # noqa: BLE001 — data is still useful without charts
        logger.warning("sheets_charts_skipped", error=str(err))

    try:
        _format_workbook(sh, dash_meta)
    except Exception as err:  # noqa: BLE001
        logger.warning("sheets_format_skipped", error=str(err))

    try:
        detail = sh.worksheet(TAB_DETAIL)
        detail.freeze(rows=1)
        sh.batch_update(
            {
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
        )
    except Exception as err:  # noqa: BLE001
        logger.warning("sheets_detail_filter_skipped", error=str(err))

    # Product tab order after Dashboard.
    try:
        requests = []
        for idx, title in enumerate(order):
            ws = sh.worksheet(title)
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": ws.id,
                            "index": idx,
                            "hidden": False,
                        },
                        "fields": "index,hidden",
                    }
                }
            )
        sh.batch_update({"requests": requests})
    except Exception as err:  # noqa: BLE001
        logger.warning("sheets_reorder_skipped", error=str(err))

    counts["_purged"] = len(purged)
    return counts
