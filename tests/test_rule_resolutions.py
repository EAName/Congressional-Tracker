"""Special-order rule resolutions must never be scoreable."""

from __future__ import annotations

import re

from vact.analysis.scoring import load_scoring_config


def _pattern() -> re.Pattern[str]:
    return re.compile(load_scoring_config().rule_resolution_title_pattern)


def test_all_rule_resolution_phrasings_are_excluded() -> None:
    """The original pattern only caught 'Providing for consideration', missing
    'Providing for further consideration' (15 rows in the historical queue) and
    'Rule providing for consideration' (13). Those would have been scoreable."""
    pat = _pattern()
    for title in (
        "Providing for consideration of H.R. 1",
        "Providing for further consideration of the bill (H.R. 627)",
        "Rule providing for consideration of the bill S. 181",
        "  providing for consideration of the Senate amendment",
        "RULE PROVIDING FOR CONSIDERATION OF H.R. 4173",
    ):
        assert pat.match(title), f"not excluded: {title!r}"


def test_substantive_bills_are_not_swept_up() -> None:
    pat = _pattern()
    for title in (
        "Affordable Insulin Now Act",
        "Small Business Jobs Act of 2010",
        "Wall Street Reform and Consumer Protection Act of 2009",
        "A bill providing loans for rural consideration projects",
    ):
        assert not pat.match(title), f"wrongly excluded: {title!r}"
