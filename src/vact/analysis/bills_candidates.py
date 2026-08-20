"""HITL candidate bill list: `data/bills_candidates.csv` (Prompt 6).

Unique key is `(bill_id, theme)`. RULE rows are proposals. HUMAN rows are never
overwritten by ingest. Scoring reads only `adjudicated=true` with axis_direction
advance|oppose.

Does not store a cosponsorship score (AGENTS.md §8).
"""

from __future__ import annotations

import csv
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from vact.analysis.scoring import ScoringConfig, _match_valence, load_scoring_config
from vact.analysis.votes import AxisDirection
from vact.paths import REPO_ROOT
from vact.sources.cosponsorship import BillRef
from vact.transforms.classify import load_rulebook, tags_for_corpus

CANDIDATES_PATH = REPO_ROOT / "data" / "bills_candidates.csv"

CSV_COLUMNS: tuple[str, ...] = (
    "bill_id",
    "congress",
    "bill_type",
    "bill_number",
    "title",
    "theme",
    "axis_direction",
    "adjudicated",
    "adjudicator",
    "adjudication_note",
    "adjudication_date",
    "source_url",
)


class CandidatesError(ValueError):
    pass


class BillCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bill_id: str
    congress: int
    bill_type: str
    bill_number: int
    title: str
    theme: str
    axis_direction: str = ""
    adjudicated: bool = False
    adjudicator: str = "RULE"
    adjudication_note: str = ""
    adjudication_date: str = ""
    source_url: str = ""

    @field_validator("bill_id", "theme", "title", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("required field is empty")
        return text

    @field_validator("adjudicated", mode="before")
    @classmethod
    def _bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no", ""}:
            return False
        raise ValueError(f"adjudicated must be boolean, got {value!r}")

    @property
    def key(self) -> tuple[str, str]:
        return (self.bill_id, self.theme)


def load_candidates(path: Path | None = None) -> list[BillCandidate]:
    dest = path or CANDIDATES_PATH
    if not dest.is_file():
        return []
    with dest.open(newline="", encoding="utf-8") as fh:
        return [BillCandidate.model_validate(rec) for rec in csv.DictReader(fh)]


def write_candidates(rows: Sequence[BillCandidate], path: Path | None = None) -> Path:
    dest = path or CANDIDATES_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r.theme, r.bill_id))
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            payload = row.model_dump()
            payload["adjudicated"] = "true" if row.adjudicated else "false"
            writer.writerow({col: payload.get(col, "") for col in CSV_COLUMNS})
    return dest


def validate_candidates(rows: Sequence[BillCandidate]) -> list[str]:
    errors: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for i, row in enumerate(rows, start=2):
        loc = f"line {i} {row.key}"
        if row.key in seen:
            errors.append(f"{loc}: duplicate key")
        else:
            seen[row.key] = i
        if row.adjudicator not in {"RULE", "HUMAN", "LLM", ""}:
            errors.append(f"{loc}: adjudicator {row.adjudicator!r}")
        if row.adjudicated:
            if row.axis_direction not in {AxisDirection.ADVANCE.value, AxisDirection.OPPOSE.value}:
                errors.append(f"{loc}: adjudicated rows need axis_direction advance|oppose")
            if row.adjudicator != "HUMAN":
                errors.append(f"{loc}: adjudicated=true requires adjudicator=HUMAN")
        elif row.axis_direction and row.axis_direction not in {
            AxisDirection.ADVANCE.value,
            AxisDirection.OPPOSE.value,
            "",
        }:
            errors.append(f"{loc}: axis_direction {row.axis_direction!r}")
    return errors


def validate_candidates_file(path: Path | None = None) -> list[BillCandidate]:
    rows = load_candidates(path)
    errors = validate_candidates(rows)
    if errors:
        raise CandidatesError("bills_candidates.csv failed validation:\n" + "\n".join(errors[:20]))
    return rows


def propose_from_bills(
    bills: Sequence[BillRef],
    *,
    scoring: ScoringConfig | None = None,
    as_of: date | None = None,
) -> list[BillCandidate]:
    """RULE proposals. No score. axis_direction is a proposal until HUMAN."""
    cfg = scoring or load_scoring_config()
    rulebook = load_rulebook()
    day = as_of.isoformat() if as_of is not None else ""
    out: list[BillCandidate] = []
    for bill in bills:
        tags = tags_for_corpus(title=bill.title, rulebook=rulebook)
        if not tags:
            continue
        congress_url = (
            f"https://www.congress.gov/bill/{bill.congress}th-congress/"
            f"{_congress_gov_type(bill.bill_type)}/{bill.number}"
        )
        for theme in tags:
            valence = _match_valence(cfg, theme, bill.title)
            axis = ""
            if valence == 1:
                axis = AxisDirection.ADVANCE.value
            elif valence == -1:
                axis = AxisDirection.OPPOSE.value
            out.append(
                BillCandidate(
                    bill_id=bill.bill_id,
                    congress=bill.congress,
                    bill_type=bill.bill_type,
                    bill_number=bill.number,
                    title=bill.title,
                    theme=theme,
                    axis_direction=axis,
                    adjudicated=False,
                    adjudicator="RULE",
                    adjudication_date=day,
                    source_url=congress_url,
                )
            )
    return out


def _congress_gov_type(bill_type: str) -> str:
    mapping = {
        "hr": "house-bill",
        "s": "senate-bill",
        "hjres": "house-joint-resolution",
        "sjres": "senate-joint-resolution",
        "hconres": "house-concurrent-resolution",
        "sconres": "senate-concurrent-resolution",
        "hres": "house-resolution",
        "sres": "senate-resolution",
    }
    return mapping.get(bill_type, bill_type)


def merge_candidates(
    existing: Sequence[BillCandidate],
    incoming: Sequence[BillCandidate],
) -> list[BillCandidate]:
    """HUMAN rows are sticky. RULE/LLM rows may refresh title and proposed axis."""
    by_key: dict[tuple[str, str], BillCandidate] = {r.key: r for r in existing}
    for row in incoming:
        prior = by_key.get(row.key)
        if prior is not None and prior.adjudicator == "HUMAN":
            continue
        by_key[row.key] = row
    return list(by_key.values())
