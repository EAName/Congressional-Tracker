"""Site disclosure payload for the static web app (Prompt 16)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vact.paths import REPO_ROOT

from vact.exports.brand import load_brand_config

DISCLOSURE_CONFIG = REPO_ROOT / "config" / "site_disclosure.yaml"


def load_disclosure_config(path: Path | None = None) -> dict[str, Any]:
    dest = path or DISCLOSURE_CONFIG
    if not dest.is_file():
        raise FileNotFoundError(f"site disclosure config not found: {dest}")
    payload = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    footer = payload.get("footer") or {}
    if not footer.get("paragraphs"):
        raise ValueError("site_disclosure.yaml footer.paragraphs is required")
    return payload


def race_disclaimer(config: dict[str, Any], race_id: str) -> str:
    race_cfg = config.get("race_page") or {}
    by_race = race_cfg.get("by_race_id") or {}
    if race_id in by_race:
        return str(by_race[race_id] or "").strip()
    return str(race_cfg.get("default_disclaimer") or "").strip()


def build_disclosure_payload(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_disclosure_config()
    brand = load_brand_config()
    footer = cfg["footer"]
    race_cfg = cfg.get("race_page") or {}
    return {
        "publisher": brand["site_name"],
        "footer": {
            "paragraphs": [str(p).strip() for p in footer["paragraphs"] if str(p).strip()],
            "methodology_label": footer.get("methodology_label", "Full methodology"),
            "methodology_href": footer.get("methodology_href", "/methodology"),
            "about_label": footer.get("about_label", "About"),
            "about_href": footer.get("about_href", "/about"),
            "corrections_label": footer.get("corrections_label", "Corrections policy"),
            "corrections_href": footer.get("corrections_href", "/corrections"),
        },
        "race_page": {
            "default_disclaimer": str(race_cfg.get("default_disclaimer") or "").strip(),
            "by_race_id": {
                str(k): str(v or "").strip() for k, v in (race_cfg.get("by_race_id") or {}).items()
            },
        },
    }
