"""Shared vote-position enum used by House and Senate parsers."""

from __future__ import annotations

from enum import StrEnum


class VotePosition(StrEnum):
    YEA = "YEA"
    NAY = "NAY"
    PRESENT = "PRESENT"
    NOT_VOTING = "NOT_VOTING"


_POSITION_ALIASES: dict[str, VotePosition] = {
    "YEA": VotePosition.YEA,
    "AYE": VotePosition.YEA,
    "NAY": VotePosition.NAY,
    "NO": VotePosition.NAY,
    "PRESENT": VotePosition.PRESENT,
    "NOT VOTING": VotePosition.NOT_VOTING,
    "NOTVOTING": VotePosition.NOT_VOTING,
}


def normalize_vote_position(raw: str | None) -> VotePosition:
    """Normalize House/Senate position strings to the canonical enum."""
    if raw is None or not raw.strip():
        raise ValueError("empty vote position")
    key = " ".join(raw.strip().upper().split())
    try:
        return _POSITION_ALIASES[key]
    except KeyError as err:
        raise ValueError(f"unrecognized vote position: {raw!r}") from err
