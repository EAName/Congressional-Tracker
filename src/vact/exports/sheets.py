"""Google Sheets audit export (gspread; service account or OAuth)."""

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
from vact.paths import REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
BATCH_ROW_CAP = 500

TAB_README = "README"
TAB_TARGET = "Target Four"
TAB_FULL = "Full Delegation"
TAB_DETAIL = "Vote Detail"

DEFAULT_OAUTH_CLIENT = Path.home() / ".config" / "gspread" / "credentials.json"
DEFAULT_OAUTH_TOKEN = Path.home() / ".config" / "gspread" / "authorized_user.json"
# Also accept a project-local (gitignored) client path.
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
    # Prefer secrets/ when the client lives there (or LOCAL path is intended).
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
        # Known caucus tracker workbook.
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
    """
    Load OAuth client JSON. Desktop (`installed`) is preferred; Web clients are
    remapped for the local-server loopback flow when redirect URIs are missing.
    """
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
    """
    Authenticate and attempt a read. On failure, print share instructions.
    """
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
    except Exception as err:  # noqa: BLE001 — surface opaque 403 as actionable copy
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

    def _cell(v: Any) -> Any:
        if v is None:
            return ""
        # Sheets JSON body cannot carry datetime.date / datetime.datetime.
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
    client, email = _open_client(interactive=False)
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
