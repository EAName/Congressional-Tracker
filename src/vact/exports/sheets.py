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
    SCORECARD_TAGS,
    corpus_vote_count,
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

# Hand-built v1 stubs. Renamed + hidden on every push so the share link is not
# the Vacant-VA-11 roster.
LEGACY_TAB_TITLES = (
    "Legislators",
    "Votes",
    "Small Business Votes",
    "Sheet5",
    "Vote Positions",
)
LEGACY_PREFIX = "_Archive · "

WORKBOOK_TITLE = "VA Congressional Vote Tracker"

DEFAULT_OAUTH_CLIENT = Path.home() / ".config" / "gspread" / "credentials.json"
DEFAULT_OAUTH_TOKEN = Path.home() / ".config" / "gspread" / "authorized_user.json"
LOCAL_OAUTH_CLIENT = REPO_ROOT / "secrets" / "oauth_client.json"
LOCAL_OAUTH_TOKEN = REPO_ROOT / "secrets" / "authorized_user.json"

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
                r.get("partisan_lean") or "",
                "YES" if r.get("is_target") else "NO",
                *[r[t] for t in SCORECARD_TAGS],
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
            "Old hand-built Legislators/Votes/Dashboard stubs are renamed _Archive · * and hidden.",
        ],
    ]


def build_dashboard_layout(
    conn,
    *,
    generated_at: str | None = None,
) -> tuple[list[list[Any]], dict[str, Any]]:
    """
    Build the Dashboard rectangle plus chart source coordinates (1-based rows).

    Layout:
      rows 1-5  title + snapshot stats
      rows 7+   category mix (A:B) and impact mix (D:E) — chart sources
      then      Target Four scorecard, then Full Delegation scorecard
    """
    ts = generated_at or generated_at_utc()
    votes = corpus_vote_count(conn)
    tagged = tagged_vote_count(conn)
    ready = publication_ready_count(conn)
    categories = vote_category_mix(conn)
    tags = impact_tag_mix(conn)
    targets = _scorecard_matrix(scorecard_rows(conn, target_four(conn, map_version="2026")))
    full = _scorecard_matrix(scorecard_rows(conn, list_delegation(conn, map_version="2026")))

    # Dual-column chart sources start at row 7.
    chart_header_row = 7
    chart_data_start = 8
    n_cat = max(len(categories), 1)
    n_tag = max(len(tags), 1)
    chart_height = max(n_cat, n_tag)
    chart_data_end = chart_data_start + chart_height - 1

    rows: list[list[Any]] = [
        ["VA Congressional Vote Tracker", "", "", "", "", "", "", ""],
        ["Democrats for Virginia · Small Business Caucus", "", "", "", "", "", "", ""],
        ["Generated (UTC)", ts, "Map version", "2026", "", "", "", ""],
        [
            "Roll calls in warehouse",
            votes,
            "Impact-tagged votes",
            tagged,
            "Human-summarized (site cards)",
            ready,
            "",
            "",
        ],
        [
            "Sources",
            "clerk.house.gov · senate.gov LIS · congress-legislators",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [],  # row 6 blank
        ["Vote category", "Count", "", "Impact tag", "Count", "", "", ""],
    ]

    for i in range(chart_height):
        cat = categories[i] if i < len(categories) else {"label": "", "count": ""}
        tag = tags[i] if i < len(tags) else {"label": "", "count": ""}
        tag_label = (
            str(tag["label"]).replace("_", " ").title() if tag["label"] else ""
        )
        rows.append(
            [
                cat["label"],
                cat["count"],
                "",
                tag_label,
                tag["count"],
                "",
                "",
                "",
            ]
        )

    rows.append([])
    rows.append(
        [
            "TARGET FOUR — districts under the proposed 2026 map leaning toward Democrats",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    target_start = len(rows) + 1  # 1-based next row
    rows.extend(targets)
    rows.append([])
    rows.append(
        [
            "FULL DELEGATION — live Yea/Nay on RULE and HUMAN impact tags",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    rows.append(
        [
            "Note: TAX_BURDEN is empty until RULE or HUMAN tags land. Em dash = no tagged votes yet.",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    full_start = len(rows) + 1
    rows.extend(full)

    meta = {
        "sheet_title": TAB_DASHBOARD,
        "category_header_row": chart_header_row,
        "category_start_row": chart_data_start,
        "category_end_row": chart_data_end,
        "impact_header_row": chart_header_row,
        "impact_start_row": chart_data_start,
        "impact_end_row": chart_data_end,
        "n_categories": len(categories),
        "n_tags": len(tags),
        "target_header_row": target_start,
        "full_header_row": full_start,
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
    targets = scorecard_rows(conn, target_four(conn, map_version="2026"))
    full = scorecard_rows(conn, list_delegation(conn, map_version="2026"))
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


def _archive_legacy_tabs(sh) -> list[str]:
    """Rename + hide hand-built v1 stubs so they are not the product surface."""
    archived: list[str] = []
    requests: list[dict[str, Any]] = []
    for ws in sh.worksheets():
        title = ws.title
        if title.startswith(LEGACY_PREFIX):
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": ws.id, "hidden": True},
                        "fields": "hidden",
                    }
                }
            )
            archived.append(title)
            continue
        if title not in LEGACY_TAB_TITLES:
            continue
        new_title = f"{LEGACY_PREFIX}{title}"
        # Avoid collision if a prior push already archived under this name.
        existing = {w.title for w in sh.worksheets()}
        if new_title in existing:
            new_title = f"{LEGACY_PREFIX}{title} ({ws.id})"
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": ws.id,
                        "title": new_title,
                        "hidden": True,
                    },
                    "fields": "title,hidden",
                }
            }
        )
        archived.append(new_title)
    if requests:
        sh.batch_update({"requests": requests})
        logger.info("sheets_legacy_archived", tabs=archived)
    return archived


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

    cat_start = meta["category_start_row"] - 1  # 0-based
    cat_end = meta["category_end_row"]  # exclusive in Sheets API when +0 for end?
    # Google Sheets API: endRowIndex is exclusive.
    cat_end_excl = meta["category_end_row"]  # already 1-based end; exclusive = same number if start is 0-based...
    # header is row 7 (1-based) = index 6; data rows 8..end inclusive → startRowIndex=6 includes header for pie
    # Pie chart source typically includes header.
    header_idx = meta["category_header_row"] - 1
    cat_end_excl = meta["category_end_row"]  # exclusive end = last data row (1-based) works as exclusive if we want rows header..last
    # For range covering rows 7..14 inclusive: startRowIndex=6, endRowIndex=14

    impact_header_idx = meta["impact_header_row"] - 1
    impact_end_excl = meta["impact_end_row"]

    requests = [
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Vote categories (full corpus)",
                        "pieChart": {
                            "legendPosition": "RIGHT_LEGEND",
                            "domain": {
                                "sourceRange": {
                                    "sources": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": header_idx,
                                            "endRowIndex": cat_end_excl,
                                            "startColumnIndex": 0,
                                            "endColumnIndex": 1,
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
                                            "startColumnIndex": 1,
                                            "endColumnIndex": 2,
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
                                "rowIndex": 6,
                                "columnIndex": 6,
                            },
                            "widthPixels": 420,
                            "heightPixels": 280,
                        }
                    },
                }
            }
        },
        {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": "Impact tags (RULE + HUMAN)",
                        "basicChart": {
                            "chartType": "COLUMN",
                            "legendPosition": "NO_LEGEND",
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "Tag"},
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
                                                    "startColumnIndex": 3,
                                                    "endColumnIndex": 4,
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
                                                    "startColumnIndex": 4,
                                                    "endColumnIndex": 5,
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
                                "rowIndex": 6,
                                "columnIndex": 12,
                            },
                            "widthPixels": 420,
                            "heightPixels": 280,
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

    # Archive stubs before writing so index-0 is not a hidden mess mid-flight.
    archived = _archive_legacy_tabs(sh)
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

    counts["_archived"] = len(archived)
    return counts
