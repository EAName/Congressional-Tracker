"""Static site generator → docs/ (GitHub Pages)."""

from __future__ import annotations

from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from vact.exports.data import (
    corpus_vote_count,
    district_votes_for_member,
    generated_at_utc,
    list_delegation,
    scorecard_rows,
    target_four,
)
from vact.paths import REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = REPO_ROOT / "templates" / "site"
DEFAULT_OUT = REPO_ROOT / "docs"


class SiteBuildError(RuntimeError):
    """Raised when activist pages cannot be rendered safely."""


def _env() -> Environment:
    if not TEMPLATE_DIR.is_dir():
        raise SiteBuildError(f"missing templates: {TEMPLATE_DIR}")
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def build_site(
    *,
    out_dir: Path | None = None,
    warehouse_path: Path | None = None,
    map_version: str = "2026",
) -> Path:
    """
    Generate mobile-first HTML into docs/.

    Fails loudly if a district-page vote lacks plain_language_summary (never
    falls back to vote_question).
    """
    dest = out_dir or DEFAULT_OUT
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "district").mkdir(parents=True, exist_ok=True)

    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        ts = generated_at_utc()
        votes = corpus_vote_count(conn)
        targets = target_four(conn, map_version=map_version)
        if len(targets) != 4:
            logger.warning(
                "target_four_count",
                expected=4,
                got=len(targets),
                map_version=map_version,
            )
        target_cards = []
        for member in targets:
            votes_for = district_votes_for_member(conn, bioguide_id=member["bioguide_id"])
            target_cards.append({"member": member, "votes": votes_for})

        delegation = list_delegation(conn, map_version=map_version)
        delegation_scores = scorecard_rows(conn, delegation)

        env = _env()
        common = {
            "generated_at_utc": ts,
            "corpus_vote_count": votes,
            "map_version": map_version,
            "brand": "Democrats for Virginia",
            "product": "Congressional Vote Tracker",
        }

        index_html = env.get_template("index.html").render(
            **common, targets=target_cards
        )
        (dest / "index.html").write_text(index_html, encoding="utf-8")

        for card in target_cards:
            n = card["member"]["district_number"]
            if n is None:
                raise SiteBuildError(f"target member missing district: {card['member']}")
            html = env.get_template("district.html").render(
                **common, member=card["member"], votes=card["votes"]
            )
            (dest / "district" / f"{n}.html").write_text(html, encoding="utf-8")

        del_html = env.get_template("delegation.html").render(
            **common, members=delegation_scores
        )
        (dest / "delegation.html").write_text(del_html, encoding="utf-8")

        meth = env.get_template("methodology.html").render(**common)
        (dest / "methodology.html").write_text(meth, encoding="utf-8")

        # Minimal stylesheet (no build step).
        (dest / "styles.css").write_text(_STYLES, encoding="utf-8")

        logger.info("site_built", out=str(dest), targets=len(target_cards), votes=votes)
        return dest
    finally:
        conn.close()


_STYLES = """\
:root {
  --ink: #0b1f33;
  --paper: #f4f7fb;
  --band: #143a5c;
  --accent: #c45c26;
  --line: #c9d6e5;
  --card: #ffffff;
  --muted: #4a6074;
  --ok: #1f6b4a;
  --nay: #8b2942;
  --font-display: "Fraunces", "Iowan Old Style", Georgia, serif;
  --font-body: "Sora", "Avenir Next", "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { font-size: 17px; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(1200px 500px at 10% -10%, #d7e6f5 0%, transparent 60%),
    linear-gradient(180deg, #eaf1f8 0%, var(--paper) 40%, #e7eef6 100%);
  font-family: var(--font-body);
  line-height: 1.5;
}
a { color: var(--band); }
.wrap { width: min(42rem, calc(100% - 2rem)); margin: 0 auto; padding: 1.25rem 0 3rem; }
.site-header {
  padding: 1.75rem 0 1rem;
  border-bottom: 1px solid var(--line);
  margin-bottom: 1.5rem;
}
.brand {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(1.8rem, 6vw, 2.6rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--band);
  margin: 0;
}
.product {
  margin: 0.35rem 0 0;
  color: var(--muted);
  font-size: 0.95rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.lede { margin: 1rem 0 0; font-size: 1.05rem; max-width: 34rem; }
nav {
  display: flex; flex-wrap: wrap; gap: 0.75rem 1rem;
  margin: 1rem 0 0; font-size: 0.92rem;
}
nav a { text-decoration: none; font-weight: 600; }
.card-list { display: grid; gap: 0.9rem; margin: 1.25rem 0; }
.card {
  display: block; background: var(--card); border: 1px solid var(--line);
  border-radius: 0.35rem; padding: 1rem 1.1rem; text-decoration: none; color: inherit;
  box-shadow: 0 1px 0 rgba(11, 31, 51, 0.04);
  transition: transform 160ms ease, border-color 160ms ease;
}
.card:hover, .card:focus-visible {
  transform: translateY(-2px);
  border-color: var(--band);
}
.card h2 { margin: 0; font-family: var(--font-display); font-size: 1.35rem; }
.card .meta { color: var(--muted); font-size: 0.9rem; margin-top: 0.25rem; }
.vote {
  border-top: 1px solid var(--line); padding: 1rem 0;
}
.vote:first-of-type { border-top: 0; }
.vote time { color: var(--muted); font-size: 0.85rem; }
.vote .summary { margin: 0.35rem 0; font-size: 1.05rem; }
.pos-YEA { color: var(--ok); font-weight: 700; }
.pos-NAY { color: var(--nay); font-weight: 700; }
.pos-PRESENT, .pos-NOT_VOTING { color: var(--muted); font-weight: 700; }
.member-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
.member-table th, .member-table td {
  text-align: left; padding: 0.55rem 0.35rem; border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.member-table th { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.site-footer {
  margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: 0.85rem;
}
@media (max-width: 520px) {
  .member-table { display: block; }
  .member-table thead { display: none; }
  .member-table tr { display: block; padding: 0.75rem 0; border-bottom: 1px solid var(--line); }
  .member-table td { display: block; border: 0; padding: 0.15rem 0; }
  .member-table td::before {
    content: attr(data-label);
    display: block; font-size: 0.7rem; text-transform: uppercase; color: var(--muted);
  }
}
"""
