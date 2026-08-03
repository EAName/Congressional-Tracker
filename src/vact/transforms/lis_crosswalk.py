"""National LIS → bioguide crosswalk built from congress-legislators."""

from __future__ import annotations

from collections.abc import Mapping

from vact.models.legislators import LegislatorRecord


class AmbiguousLisMappingError(ValueError):
    """Raised when one lis_id maps to multiple bioguide IDs."""


class UnresolvedLisMemberError(LookupError):
    """Raised when one or more Senate lis_member_id values cannot be resolved."""

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = sorted(set(unresolved))
        super().__init__(
            "unresolved lis_member_id values: " + ", ".join(self.unresolved)
        )


def build_lis_bioguide_crosswalk(
    records: list[LegislatorRecord],
) -> dict[str, str]:
    """
    Map Senate LIS member IDs to bioguide_id.

    Fail loudly on ambiguous mappings (same lis_id, different bioguides).
    """
    mapping: dict[str, str] = {}
    for record in records:
        lis = record.id.lis
        if not lis:
            continue
        bioguide = record.id.bioguide
        if lis in mapping and mapping[lis] != bioguide:
            raise AmbiguousLisMappingError(
                f"lis_id {lis!r} maps to both {mapping[lis]!r} and {bioguide!r}"
            )
        mapping[lis] = bioguide
    return mapping


def resolve_lis_member_id(
    lis_member_id: str,
    crosswalk: Mapping[str, str],
) -> str:
    try:
        return crosswalk[lis_member_id]
    except KeyError as err:
        raise UnresolvedLisMemberError([lis_member_id]) from err
