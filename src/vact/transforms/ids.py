"""Canonical natural keys for bills and roll calls."""

from __future__ import annotations

import re
from dataclasses import dataclass

_BILL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*H\.?\s*R\.?\s*(\d+)\s*$", re.I), "hr"),
    (re.compile(r"^\s*H\.?\s*RES\.?\s*(\d+)\s*$", re.I), "hres"),
    (re.compile(r"^\s*H\.?\s*J\.?\s*RES\.?\s*(\d+)\s*$", re.I), "hjres"),
    (re.compile(r"^\s*H\.?\s*CON\.?\s*RES\.?\s*(\d+)\s*$", re.I), "hconres"),
    (re.compile(r"^\s*S\.?\s*RES\.?\s*(\d+)\s*$", re.I), "sres"),
    (re.compile(r"^\s*S\.?\s*J\.?\s*RES\.?\s*(\d+)\s*$", re.I), "sjres"),
    (re.compile(r"^\s*S\.?\s*CON\.?\s*RES\.?\s*(\d+)\s*$", re.I), "sconres"),
    (re.compile(r"^\s*S\.?\s*(\d+)\s*$", re.I), "s"),
    (re.compile(r"^\s*PN\s*([\w-]+)\s*$", re.I), "pn"),
)


@dataclass(frozen=True)
class BillRef:
    bill_id: str
    congress: int
    bill_type: str
    bill_number: int | None
    bill_number_raw: str | None


def canonical_vote_id(chamber: str, congress: int, session: int, roll_number: int) -> str:
    """Return h-119-1-156 or s-119-2-380."""
    prefix = {"House": "h", "Senate": "s"}.get(chamber)
    if prefix is None:
        raise ValueError(f"unsupported chamber for vote_id: {chamber!r}")
    return f"{prefix}-{congress}-{session}-{roll_number}"


def normalize_vote_type(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    return re.sub(r"[\s\-]+", "_", raw.strip().upper())


def parse_bill_ref(legis_or_document: str | None, congress: int) -> BillRef | None:
    """
    Parse Clerk/LIS bill labels into canonical bill_id.

    Examples: 'H R 2966' -> hr-2966-119; 'S. 1582' -> s-1582-119;
    'PN11-18' -> pn-11-18-119.
    """
    if legis_or_document is None:
        return None
    text = " ".join(legis_or_document.strip().split())
    if not text:
        return None

    for pattern, bill_type in _BILL_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        raw_num = match.group(1)
        number: int | None
        if bill_type == "pn":
            number = int(raw_num) if raw_num.isdigit() else None
            bill_id = f"pn-{raw_num.lower()}-{congress}"
        else:
            number = int(raw_num)
            bill_id = f"{bill_type}-{number}-{congress}"
        return BillRef(
            bill_id=bill_id,
            congress=congress,
            bill_type=bill_type,
            bill_number=number,
            bill_number_raw=raw_num,
        )
    return None


_PASSED_TRUE = re.compile(
    r"(?i)\b(passed|agreed to|confirmed|adopted|bill passed|nomination confirmed|"
    r"cloture motion agreed to|motion (?:to proceed )?agreed to)\b"
)
_PASSED_FALSE = re.compile(
    r"(?i)\b(failed|rejected|defeated|not confirmed|not agreed|"
    r"cloture motion rejected|motion rejected)\b"
)


def infer_passed(result: str | None) -> bool | None:
    if result is None or not result.strip():
        return None
    if _PASSED_TRUE.search(result):
        return True
    if _PASSED_FALSE.search(result):
        return False
    return None
