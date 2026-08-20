"""Brand identity config → static web payloads (rebrand)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from vact.paths import REPO_ROOT

BRAND_CONFIG = REPO_ROOT / "config" / "brand.json"
BLOCKLIST_CONFIG = REPO_ROOT / "config" / "brand_blocklist.yaml"
ABOUT_MD = REPO_ROOT / "content" / "about.md"


def load_brand_config(path: Path | None = None) -> dict[str, Any]:
    dest = path or BRAND_CONFIG
    if not dest.is_file():
        raise FileNotFoundError(f"brand config missing: {dest}")
    payload = json.loads(dest.read_text(encoding="utf-8"))
    required = ("site_name", "tagline", "canonical_base", "github")
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"brand.json missing keys: {missing}")
    return payload


def load_blocklist_config(path: Path | None = None) -> dict[str, Any]:
    dest = path or BLOCKLIST_CONFIG
    return yaml.safe_load(dest.read_text(encoding="utf-8")) or {}


def _inline_md(text: str) -> str:
    out = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return out


def parse_about_markdown(path: Path | None = None) -> dict[str, Any]:
    dest = path or ABOUT_MD
    if not dest.is_file():
        raise FileNotFoundError(f"about markdown missing: {dest}")
    raw = dest.read_text(encoding="utf-8")
    title = "About"
    intro = ""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = {"heading": line[3:].strip(), "paragraphs": []}
            continue
        if not line.strip():
            continue
        if current is None:
            intro = (intro + " " + line.strip()).strip() if intro else line.strip()
        else:
            current["paragraphs"].append(_inline_md(line.strip()))
    if current:
        sections.append(current)
    return {
        "title": title,
        "intro": _inline_md(intro) if intro else "",
        "sections": sections,
    }


def build_brand_payload(
    config: dict[str, Any] | None = None,
    *,
    include_legacy: bool = False,
) -> dict[str, Any]:
    cfg = config or load_brand_config()
    gh = cfg["github"]
    payload: dict[str, Any] = {
        "site_name": cfg["site_name"],
        "site_name_note": cfg.get("site_name_note", ""),
        "tagline": cfg["tagline"],
        "product_name": cfg.get("product_name", cfg["site_name"]),
        "domain": cfg.get("domain", ""),
        "domain_note": cfg.get("domain_note", ""),
        "canonical_base": cfg["canonical_base"].rstrip("/"),
        "publisher_line": cfg.get("publisher_line", "Independent analysis"),
        "github": gh,
        "social": cfg.get("social") or {},
        "status": cfg.get("status", "placeholder"),
    }
    if include_legacy:
        payload["legacy"] = cfg.get("legacy") or {}
        payload["redirect_paths"] = cfg.get("redirect_paths") or []
    return payload


def build_about_payload(path: Path | None = None) -> dict[str, Any]:
    about = parse_about_markdown(path)
    brand = load_brand_config()
    about["repo_url"] = brand["github"]["repo_url"]
    about["methodology_href"] = "/methodology"
    about["symmetry_href"] = "/methodology#falsification"
    return about


def scan_blocklist_violations(
    *,
    root: Path | None = None,
    blocklist: dict[str, Any] | None = None,
) -> list[str]:
    """Return human-readable violations of the old-brand blocklist."""
    repo = root or REPO_ROOT
    cfg = blocklist or load_blocklist_config()
    terms = [str(t) for t in (cfg.get("terms") or []) if str(t).strip()]
    allow = {str(p).rstrip("/") for p in (cfg.get("allow_paths") or [])}
    globs = cfg.get("scan_globs") or []
    violations: list[str] = []
    seen: set[str] = set()

    def allowed(rel: str) -> bool:
        for prefix in allow:
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
        return False

    files: list[Path] = []
    for pattern in globs:
        files.extend(repo.glob(pattern))

    for path in sorted(set(files)):
        if not path.is_file():
            continue
        rel = str(path.relative_to(repo))
        if allowed(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for term in terms:
            if term in text:
                key = f"{rel}:{term}"
                if key not in seen:
                    seen.add(key)
                    violations.append(f"{rel} contains blocklisted term {term!r}")
    return violations
