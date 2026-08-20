"""Disclosure export tests (Prompt 16)."""

from __future__ import annotations

from vact.exports.disclosure import build_disclosure_payload, load_disclosure_config, race_disclaimer


def test_disclosure_payload_from_config() -> None:
    cfg = load_disclosure_config()
    payload = build_disclosure_payload(cfg)
    assert payload["publisher"]
    assert "About" in payload["footer"]["about_label"] or payload["footer"].get("about_href")
    assert len(payload["footer"]["paragraphs"]) >= 2
    assert payload["footer"]["methodology_href"] == "/methodology"
    assert payload["footer"]["corrections_href"] == "/corrections"


def test_race_disclaimer_empty_by_default() -> None:
    cfg = load_disclosure_config()
    assert race_disclaimer(cfg, "va-02") == ""
