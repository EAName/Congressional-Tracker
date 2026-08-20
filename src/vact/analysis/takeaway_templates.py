"""Takeaway sentence templates and advocacy lint (Prompt 17).

Templates must describe scores, gaps, and probabilities. They must not exhort.
The mirror test swaps party labels and signs; structure must stay identical.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

from vact.paths import REPO_ROOT

ADVOCACY_PATH = REPO_ROOT / "config" / "advocacy_verbs.yaml"

REGISTERED_TEMPLATES: dict[str, str] = {
    "seat_takeaway_flip": (
        "VA-{district} crosses 50% Democratic win probability if the national "
        "environment reaches D+{threshold:g}."
    ),
    "seat_takeaway_always_dem": (
        "VA-{district} stays above 50% Democratic win probability even if the "
        "national environment reaches D{low:+g}."
    ),
    "seat_takeaway_never_dem": (
        "VA-{district} stays below 50% Democratic win probability even if the "
        "national environment reaches D{high:+g}."
    ),
    "seat_plain_tossup": "The race is a toss-up",
    "seat_plain_dem_favorite": "Democrats are modest favorites, roughly {n} in 5",
    "seat_plain_rep_favorite": "Republicans are modest favorites, roughly {n} in 5",
}


@lru_cache(maxsize=1)
def load_advocacy_verbs(path: Path | None = None) -> tuple[str, ...]:
    dest = path or ADVOCACY_PATH
    payload = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    verbs = payload.get("verbs") or []
    return tuple(str(v).strip().lower() for v in verbs if str(v).strip())


def find_advocacy_violations(text: str, verbs: tuple[str, ...] | None = None) -> list[str]:
    """Return matched advocacy tokens in text."""
    vocab = verbs if verbs is not None else load_advocacy_verbs()
    hits: list[str] = []
    lower = text.lower()
    for verb in vocab:
        if " " in verb:
            if verb in lower:
                hits.append(verb)
        elif re.search(rf"\b{re.escape(verb)}\b", lower):
            hits.append(verb)
    return hits


def lint_registered_templates(verbs: tuple[str, ...] | None = None) -> list[tuple[str, list[str]]]:
    """Lint every registered template string."""
    out: list[tuple[str, list[str]]] = []
    for name, tmpl in REGISTERED_TEMPLATES.items():
        hits = find_advocacy_violations(tmpl, verbs=verbs)
        if hits:
            out.append((name, hits))
    return out


def mirror_party_text(text: str) -> str:
    """Swap party labels and flip D+/R+ margin signs for symmetry tests."""
    out = text
    out = out.replace("Democratic", "__TMP_DEM__")
    out = out.replace("Democrat", "Republican")
    out = out.replace("__TMP_DEM__", "Republican")
    out = out.replace("Democrats", "Republicans")
    out = out.replace("Republicans", "__TMP_REP_PL__")
    out = out.replace("Republican", "Democratic")
    out = out.replace("__TMP_REP_PL__", "Democrats")

    def flip_sign(match: re.Match[str]) -> str:
        sign = match.group(1)
        num = match.group(2)
        if sign == "+":
            return f"R+{num}"
        if sign == "-":
            return f"R{sign}{num}"
        return match.group(0)

    out = re.sub(r"D([+-])(\d+(?:\.\d+)?)", flip_sign, out)
    return out


def mirror_structure_equal(a: str, b: str) -> bool:
    """True when strings differ only by party tokens and D/R margin prefixes."""
    def skeleton(text: str) -> str:
        s = text
        s = re.sub(r"\bDemocrats?\b", "PARTY_A", s, flags=re.I)
        s = re.sub(r"\bRepublicans?\b", "PARTY_B", s, flags=re.I)
        s = re.sub(r"\bDemocratic\b", "PARTY_A", s, flags=re.I)
        s = re.sub(r"[DR][+-]?\d+(?:\.\d+)?", "MARGIN", s)
        return s

    return skeleton(a) == skeleton(b)


def run_mirror_fixture(template: str, *, render: Callable[..., str], **kwargs: object) -> bool:
    """Render template with kwargs and mirrored kwargs; compare structure."""
    original = render(template, **kwargs)
    mirrored_kwargs = dict(kwargs)
    if "party" in mirrored_kwargs and mirrored_kwargs["party"] == "Democrat":
        mirrored_kwargs["party"] = "Republican"
    elif "party" in mirrored_kwargs and mirrored_kwargs["party"] == "Republican":
        mirrored_kwargs["party"] = "Democrat"
    mirrored = mirror_party_text(render(template, **mirrored_kwargs))
    return mirror_structure_equal(original, mirrored)


def render_template(name: str, **kwargs: object) -> str:
    tmpl = REGISTERED_TEMPLATES[name]
    return tmpl.format(**kwargs)
