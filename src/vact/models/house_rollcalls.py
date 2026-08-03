"""Pydantic contracts for House Clerk EVS roll-call XML."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from vact.models.votes import VotePosition


class HouseVoteTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yea: int = Field(ge=0)
    nay: int = Field(ge=0)
    present: int = Field(ge=0)
    not_voting: int = Field(ge=0)


class HouseVoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    congress: int
    session: int
    chamber: str
    roll_number: int
    legis_num: str | None = None
    vote_question: str | None = None
    vote_type: str | None = None
    vote_result: str | None = None
    action_date: date
    action_time: str | None = None
    vote_desc: str | None = None
    majority: str | None = None
    amendment_num: str | None = None
    amendment_author: str | None = None
    totals: HouseVoteTotals
    source_url: str


class HouseMemberVoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bioguide_id: str
    name: str
    party: str | None = None
    state: str | None = None
    role: str | None = None
    position: VotePosition
