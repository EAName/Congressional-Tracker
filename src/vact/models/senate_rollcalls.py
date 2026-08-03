"""Pydantic contracts for Senate LIS roll-call XML."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from vact.models.votes import VotePosition


class SenateDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str  # document | nomination
    congress: int | None = None
    document_type: str | None = None
    document_number: str | None = None
    name: str | None = None
    title: str | None = None
    short_title: str | None = None


class SenateAmendmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amendment_number: str | None = None
    amendment_to_amendment_number: str | None = None
    amendment_to_document_number: str | None = None
    amendment_purpose: str | None = None


class SenateVoteTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yea: int = Field(ge=0)
    nay: int = Field(ge=0)
    present: int = Field(ge=0)
    not_voting: int = Field(ge=0)


class SenateVoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    congress: int
    session: int
    congress_year: int
    roll_number: int
    vote_date: date
    vote_question: str | None = None
    vote_question_text: str | None = None
    vote_title: str | None = None
    vote_result: str | None = None
    vote_result_text: str | None = None
    majority_requirement: str | None = None
    document: SenateDocumentRef | None = None
    amendment: SenateAmendmentRef | None = None
    totals: SenateVoteTotals
    source_url: str


class SenateMemberVoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bioguide_id: str
    lis_member_id: str
    name: str
    party: str | None = None
    state: str | None = None
    position: VotePosition
