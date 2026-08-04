"""Static site generator → docs/ (GitHub Pages)."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from vact.exports.data import (
    SCORECARD_TAGS,
    corpus_vote_count,
    district_votes_for_member,
    generated_at_utc,
    heatmap_rows,
    impact_tag_mix,
    list_delegation,
    publication_ready_count,
    scorecard_rows,
    tagged_vote_count,
    target_four,
    vote_category_mix,
)
from vact.paths import REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = REPO_ROOT / "templates" / "site"
DEFAULT_OUT = REPO_ROOT / "docs"
STYLES_PATH = TEMPLATE_DIR / "styles.css"


class SiteBuildError(RuntimeError):
    """Raised when activist pages cannot be rendered safely."""


def _env() -> Environment:
    if not TEMPLATE_DIR.is_dir():
        raise SiteBuildError(f"missing templates: {TEMPLATE_DIR}")
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["tojson"] = lambda v: Markup(json.dumps(v, default=str))
    return env


def build_site(
    *,
    out_dir: Path | None = None,
    warehouse_path: Path | None = None,
    map_version: str = "2026",
) -> Path:
    """
    Generate mobile-first HTML into docs/ with charts and a delegation heatmap.

    Vote narrative cards still require plain_language_summary (never fall back
    to vote_question). Scorecard/heatmap cells are live Yea/Nay counts.
    """
    dest = out_dir or DEFAULT_OUT
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "district").mkdir(parents=True, exist_ok=True)

    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        ts = generated_at_utc()
        votes = corpus_vote_count(conn)
        tagged = tagged_vote_count(conn)
        ready = publication_ready_count(conn)
        categories = vote_category_mix(conn)
        tags = impact_tag_mix(conn)

        targets = target_four(conn, map_version=map_version)
        target_cards = []
        for member in targets:
            votes_for = district_votes_for_member(
                conn, bioguide_id=member["bioguide_id"]
            )
            score = scorecard_rows(conn, [member])[0]
            target_cards.append(
                {
                    "member": member,
                    "votes": votes_for,
                    "score": score,
                    "heatmap": heatmap_rows([score])[0],
                }
            )

        delegation = list_delegation(conn, map_version=map_version)
        delegation_scores = scorecard_rows(conn, delegation)
        heat = heatmap_rows(delegation_scores)

        house_members = [m for m in delegation if m["chamber"] == "House"]
        district_pages = []
        for member in house_members:
            n = member["district_number"]
            if n is None:
                continue
            votes_for = district_votes_for_member(
                conn, bioguide_id=member["bioguide_id"]
            )
            score = scorecard_rows(conn, [member])[0]
            district_pages.append(
                {
                    "member": member,
                    "votes": votes_for,
                    "score": score,
                    "heatmap": heatmap_rows([score])[0],
                }
            )

        env = _env()
        common = {
            "generated_at_utc": ts,
            "corpus_vote_count": votes,
            "tagged_vote_count": tagged,
            "publication_ready_count": ready,
            "map_version": map_version,
            "brand": "Democrats for Virginia",
            "product": "Congressional Vote Tracker",
            "scorecard_tags": SCORECARD_TAGS,
            "category_mix": categories,
            "impact_mix": tags,
            "category_chart": {
                "labels": [c["label"] for c in categories],
                "values": [c["count"] for c in categories],
            },
            "impact_chart": {
                "labels": [t["label"].replace("_", " ").title() for t in tags],
                "values": [t["count"] for t in tags],
            },
        }

        (dest / "index.html").write_text(
            env.get_template("index.html").render(
                **common, targets=target_cards, heatmap=heat
            ),
            encoding="utf-8",
        )

        for page in district_pages:
            n = page["member"]["district_number"]
            (dest / "district" / f"{n}.html").write_text(
                env.get_template("district.html").render(**common, **page),
                encoding="utf-8",
            )

        (dest / "delegation.html").write_text(
            env.get_template("delegation.html").render(
                **common, members=delegation_scores, heatmap=heat
            ),
            encoding="utf-8",
        )

        (dest / "methodology.html").write_text(
            env.get_template("methodology.html").render(**common),
            encoding="utf-8",
        )

        styles = (
            STYLES_PATH.read_text(encoding="utf-8")
            if STYLES_PATH.is_file()
            else _FALLBACK_STYLES
        )
        (dest / "styles.css").write_text(styles, encoding="utf-8")
        (dest / "tracker.js").write_text(
            (TEMPLATE_DIR / "tracker.js").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        logger.info(
            "site_built",
            out=str(dest),
            targets=len(target_cards),
            districts=len(district_pages),
            votes=votes,
            publication_ready=ready,
        )
        return dest
    finally:
        conn.close()


_FALLBACK_STYLES = "body{font-family:sans-serif;margin:1rem;}\n"
