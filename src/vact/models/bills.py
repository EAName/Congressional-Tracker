"""Pydantic contract for Congress.gov bill-detail JSON (policy area + subjects)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class BillDetail(BaseModel):
    """Enrichment fields for an existing dim_bill row, from the Congress.gov API.

    Only fields we actually persist. `policy_area` is the curated single-label
    topic ("Commerce", "Taxation", "Health", ...) that anchors classification;
    `subjects` are the finer legislative subject terms joined for corpus matching.
    """

    model_config = ConfigDict(extra="ignore")

    bill_id: str
    policy_area: str | None = None
    official_title: str | None = None
    short_title: str | None = None
    introduced_date: date | None = None
    sponsor_bioguide: str | None = None
    subjects: tuple[str, ...] = ()

    @property
    def subjects_text(self) -> str | None:
        return " | ".join(self.subjects) if self.subjects else None
