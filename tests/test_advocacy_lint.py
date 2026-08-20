"""Advocacy lint and mirror tests for takeaway templates (Prompt 17)."""

from __future__ import annotations

from vact.analysis.takeaway_templates import (
    REGISTERED_TEMPLATES,
    find_advocacy_violations,
    lint_registered_templates,
    mirror_party_text,
    mirror_structure_equal,
    render_template,
)


def test_registered_templates_pass_advocacy_lint() -> None:
    assert lint_registered_templates() == []


def test_advocacy_lint_catches_exhortation() -> None:
    hits = find_advocacy_violations("Please vote for the candidate.")
    assert "vote" in hits


def test_mirror_structure_on_flip_threshold_template() -> None:
    original = render_template("seat_takeaway_flip", district=2, threshold=4.5)
    mirrored = mirror_party_text(
        render_template("seat_takeaway_flip", district=2, threshold=4.5)
    )
    assert mirror_structure_equal(original, mirrored)


def test_seeded_bad_template_would_fail_lint() -> None:
    bad = "Democrats must defeat the incumbent."
    assert find_advocacy_violations(bad)
    assert all(
        not find_advocacy_violations(tmpl) for tmpl in REGISTERED_TEMPLATES.values()
    )
