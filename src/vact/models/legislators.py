"""Pydantic v2 contracts for unitedstates/congress-legislators YAML payloads."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LegislatorIds(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bioguide: str
    thomas: str | None = None
    lis: str | None = None
    govtrack: int | None = None
    opensecrets: str | None = None
    icpsr: int | None = None
    fec: list[str] | None = None
    cspan: int | None = None
    wikipedia: str | None = None
    ballotpedia: str | None = None
    votesmart: int | None = None


class LegislatorName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first: str | None = None
    middle: str | None = None
    last: str | None = None
    suffix: str | None = None
    nickname: str | None = None
    official_full: str | None = None


class LegislatorBio(BaseModel):
    model_config = ConfigDict(extra="ignore")

    birthday: date | None = None
    gender: str | None = None


class LegislatorTerm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["rep", "sen"]
    start: date
    end: date
    state: str
    district: int | None = None
    party: str | None = None
    class_: int | None = Field(default=None, alias="class")
    url: str | None = None
    address: str | None = None
    phone: str | None = None
    fax: str | None = None
    contact_form: str | None = None
    office: str | None = None
    state_rank: str | None = None
    rss_url: str | None = None


class LegislatorRecord(BaseModel):
    """One legislator document from legislators-current/historical.yaml."""

    model_config = ConfigDict(extra="ignore")

    id: LegislatorIds
    name: LegislatorName
    bio: LegislatorBio | None = None
    terms: list[LegislatorTerm]


class DistrictOffice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    address: str | None = None
    suite: str | None = None
    building: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    fax: str | None = None

    @field_validator("suite", "zip", "phone", "fax", "address", "building", "city", mode="before")
    @classmethod
    def coerce_optional_str(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value)


class DistrictOfficesRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: LegislatorIds
    offices: list[DistrictOffice] = Field(default_factory=list)


class DimLegislatorRow(BaseModel):
    """Warehouse-facing SCD2 row for Virginia delegation terms."""

    model_config = ConfigDict(extra="forbid")

    bioguide_id: str
    govtrack_id: int | None = None
    icpsr_id: int | None = None
    lis_member_id: str | None = None
    full_name: str
    chamber: Literal["House", "Senate"]
    state: str
    district_current: int | None = None
    party: str | None = None
    term_start: date
    term_end: date
    first_elected: int
    is_incumbent: bool
    website: str | None = None

    @field_validator("state")
    @classmethod
    def state_must_be_va(cls, value: str) -> str:
        if value != "VA":
            raise ValueError(f"dim_legislator is VA-scoped; got state={value!r}")
        return value
