"""Brand blocklist CI (rebrand)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vact.exports.brand import load_brand_config, scan_blocklist_violations
from vact.paths import REPO_ROOT


def test_brand_config_loads() -> None:
    cfg = load_brand_config()
    assert cfg["site_name"]
    assert cfg["canonical_base"].startswith("https://")


def test_blocklist_clean_tree() -> None:
    violations = scan_blocklist_violations(root=REPO_ROOT)
    assert violations == [], "\n".join(violations)


def test_blocklist_fails_on_seeded_violation(tmp_path: Path) -> None:
    bad = tmp_path / "web" / "data"
    bad.mkdir(parents=True)
    (bad / "evil.json").write_text('{"x": "Democrats for Virginia"}', encoding="utf-8")
    violations = scan_blocklist_violations(root=tmp_path)
    assert any("Democrats for Virginia" in v for v in violations)


def test_redirect_paths_count() -> None:
    paths = load_brand_config().get("redirect_paths") or []
    assert len(paths) >= 20


def test_next_config_redirect_matrix() -> None:
    """308 redirects: each legacy host × each redirect path."""
    brand = load_brand_config()
    legacy = brand.get("legacy") or {}
    hosts = [legacy.get("old_domain"), legacy.get("old_domain_www")]
    hosts = [h for h in hosts if h]
    paths = brand.get("redirect_paths") or []
    assert len(hosts) >= 1
    assert len(paths) >= 20
    assert len(hosts) * len(paths) >= 20
