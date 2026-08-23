"""Inter-rater reliability for valence adjudication.

The external challenge to a scorecard like this is not "your code is wrong", it
is "your judgment calls all happen to favour one side". Documentation cannot
answer that; an independent coder can.

The workflow is: draw a blind sample from the adjudicated set, hand it to a
second person who has not seen the first coder's calls or any party breakdown,
then compare. The agreement rate — and specifically *where* the two disagree —
is the evidence. A published disagreement rate is a stronger claim than any
amount of methodology prose, because it is falsifiable.

Nothing here adjudicates. It draws the sample and scores the comparison.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from vact.paths import DATA_DIR

SAMPLE_PATH = DATA_DIR / "irr_sample.csv"
SAMPLE_COLUMNS = (
    "vote_id",
    "impact_tag",
    "vote_date",
    "bill_id",
    "title",
    "crs_lead",
    "valence",   # the second coder fills this, blind
    "notes",
)


def _stable_order(units: Sequence[dict[str, str]], seed: str) -> list[dict[str, str]]:
    """Deterministic shuffle. A reproducible sample is auditable; a random one
    invites 'you picked the agreeable ones'."""
    def key(u: dict[str, str]) -> str:
        raw = f"{seed}:{u['vote_id']}:{u['impact_tag']}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    return sorted(units, key=key)


def draw_sample(
    units: Sequence[dict[str, str]],
    *,
    n: int,
    seed: str = "irr-v1",
) -> list[dict[str, str]]:
    """Blind sample of adjudicated units, with the first coder's call removed."""
    picked = _stable_order(units, seed)[: max(0, n)]
    out = []
    for u in picked:
        row = {c: "" for c in SAMPLE_COLUMNS}
        for c in ("vote_id", "impact_tag", "vote_date", "bill_id", "title", "crs_lead"):
            row[c] = str(u.get(c) or "")
        out.append(row)
    return out


def write_sample(rows: Sequence[dict[str, str]], path: Path | None = None) -> Path:
    dest = path or SAMPLE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    sio = io.StringIO()
    w = csv.DictWriter(sio, fieldnames=list(SAMPLE_COLUMNS), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    dest.write_text(sio.getvalue(), encoding="utf-8")
    return dest


@dataclass
class Agreement:
    n: int
    agreed: int
    disagreements: list[dict[str, Any]]

    @property
    def rate(self) -> float | None:
        return None if not self.n else self.agreed / self.n

    def cohen_kappa(self, first: list[int], second: list[int]) -> float | None:
        """Chance-corrected agreement. Raw agreement flatters a coder who marks
        everything the same way — which is exactly the failure mode a critic
        will allege."""
        if not first:
            return None
        labels = sorted(set(first) | set(second))
        n = len(first)
        po = sum(1 for a, b in zip(first, second) if a == b) / n
        pe = sum(
            (first.count(l) / n) * (second.count(l) / n) for l in labels
        )
        if pe >= 1.0:
            return None
        return (po - pe) / (1.0 - pe)


def compare(
    sample_rows: Sequence[dict[str, str]],
    adjudicated: dict[tuple[str, str], int],
) -> tuple[Agreement, float | None]:
    """Second coder's file vs the committed adjudication."""
    first: list[int] = []
    second: list[int] = []
    disagreements: list[dict[str, Any]] = []
    for row in sample_rows:
        raw = (row.get("valence") or "").strip().replace("+", "")
        if raw not in {"1", "-1", "0"}:
            continue
        key = (row["vote_id"], row["impact_tag"])
        if key not in adjudicated:
            continue
        a, b = adjudicated[key], int(raw)
        first.append(a)
        second.append(b)
        if a != b:
            disagreements.append(
                {
                    "vote_id": row["vote_id"],
                    "impact_tag": row["impact_tag"],
                    "title": row.get("title", ""),
                    "first_coder": a,
                    "second_coder": b,
                }
            )
    agree = Agreement(
        n=len(first),
        agreed=sum(1 for a, b in zip(first, second) if a == b),
        disagreements=disagreements,
    )
    return agree, agree.cohen_kappa(first, second)
