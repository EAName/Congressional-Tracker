"""Impact taxonomy classifier (rules primary; optional LLM assist)."""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

from vact.http_client import create_client
from vact.paths import DATA_DIR, REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

logger = structlog.get_logger(__name__)

REPORTS_DIR = DATA_DIR / "reports"
REVIEW_QUEUE_PATH = REPORTS_DIR / "review_queue.csv"
RECLASSIFY_DIFF_PATH = REPORTS_DIR / "reclassify_diff.md"
RULES_PATH = REPO_ROOT / "config" / "impact_rules.yaml"

IMPACT_TAGS = (
    "ACCESS_TO_CAPITAL",
    "TAX_BURDEN",
    "FEDERAL_CONTRACTING",
    "HEALTH_COSTS",
    "INPUT_COSTS",
    "REGULATORY_BURDEN",
    "WORKFORCE",
)

EXCLUDED_CATEGORIES = frozenset({"NOMINATION", "CLOTURE"})


@dataclass(frozen=True)
class Classification:
    vote_id: str
    impact_tag: str
    confidence: float
    classified_by: str  # RULE | LLM | HUMAN


@dataclass
class Rulebook:
    version: int
    exclude_categories: set[str]
    tag_patterns: dict[str, list[re.Pattern[str]]]
    llm_eligible_patterns: list[re.Pattern[str]]


def load_rulebook(path: Path | None = None) -> Rulebook:
    rules_path = path or RULES_PATH
    payload = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    tag_patterns: dict[str, list[re.Pattern[str]]] = {}
    for tag, entries in (payload.get("tags") or {}).items():
        if tag not in IMPACT_TAGS:
            raise ValueError(f"unknown impact tag in rulebook: {tag}")
        compiled: list[re.Pattern[str]] = []
        for entry in entries or []:
            raw = entry["pattern"] if isinstance(entry, dict) else str(entry)
            compiled.append(re.compile(raw, re.IGNORECASE))
        tag_patterns[tag] = compiled
    llm_patterns = [
        re.compile(p, re.IGNORECASE) for p in (payload.get("llm_eligible_patterns") or [])
    ]
    excludes = set(payload.get("exclude_categories") or list(EXCLUDED_CATEGORIES))
    return Rulebook(
        version=int(payload.get("version") or 1),
        exclude_categories=excludes,
        tag_patterns=tag_patterns,
        llm_eligible_patterns=llm_patterns,
    )


def _corpus_text(
    question: str | None,
    title: str | None,
    short_title: str | None,
    policy_area: str | None,
) -> str:
    return " || ".join(
        part for part in (question, title, short_title, policy_area) if part
    )


def classify_rules(
    *,
    vote_id: str,
    vote_category: str,
    vote_question: str | None,
    title: str | None,
    short_title: str | None,
    policy_area: str | None,
    rulebook: Rulebook,
) -> list[Classification]:
    if vote_category in rulebook.exclude_categories:
        return []
    text = _corpus_text(vote_question, title, short_title, policy_area)
    hits: list[Classification] = []
    for tag, patterns in rulebook.tag_patterns.items():
        if any(p.search(text) for p in patterns):
            hits.append(
                Classification(
                    vote_id=vote_id,
                    impact_tag=tag,
                    confidence=1.0,
                    classified_by="RULE",
                )
            )
    return hits


def is_llm_eligible(text: str, rulebook: Rulebook) -> bool:
    return any(p.search(text) for p in rulebook.llm_eligible_patterns)


def _llm_classify(*, vote_id: str, text: str) -> list[Classification]:
    """
    Optional Stage-2 classifier. Requires OPENAI_API_KEY or VACT_LLM_API_KEY.

    Returns classifications with classified_by='LLM'. Callers gate on
    confidence >= 0.8 before writing to bridge_vote_impact.
    """
    api_key = os.environ.get("VACT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.info("llm_classify_skipped", reason="no API key", vote_id=vote_id)
        return []

    base_url = os.environ.get("VACT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("VACT_LLM_MODEL", "gpt-4o-mini")
    schema = {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "impact_tag": {"type": "string", "enum": list(IMPACT_TAGS)},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "rationale": {"type": "string"},
                    },
                    "required": ["impact_tag", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tags"],
        "additionalProperties": False,
    }
    prompt = (
        "Classify this congressional vote for small-business impact tags. "
        "Only assign a tag when the measure materially affects Virginia small "
        "businesses on that dimension. Return JSON matching the schema.\n\n"
        f"vote_id: {vote_id}\ntext: {text}"
    )

    with create_client(
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    ) as http:
        resp = http.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a legislative classifier."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "impact_tags",
                        "schema": schema,
                        "strict": True,
                    },
                },
                "temperature": 0,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)

    out: list[Classification] = []
    for item in parsed.get("tags") or []:
        tag = item["impact_tag"]
        if tag not in IMPACT_TAGS:
            continue
        out.append(
            Classification(
                vote_id=vote_id,
                impact_tag=tag,
                confidence=float(item["confidence"]),
                classified_by="LLM",
            )
        )
    return out


def _upsert_bridge(conn, rows: list[Classification]) -> int:
    """Upsert bridge rows. HUMAN always wins; RULE beats LLM; never downgrade HUMAN."""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO bridge_vote_impact AS t (vote_id, impact_tag, confidence, classified_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (vote_id, impact_tag) DO UPDATE SET
            confidence = CASE
                WHEN t.classified_by = 'HUMAN' THEN t.confidence
                ELSE excluded.confidence
            END,
            classified_by = CASE
                WHEN t.classified_by = 'HUMAN' THEN 'HUMAN'
                WHEN excluded.classified_by = 'HUMAN' THEN 'HUMAN'
                WHEN t.classified_by = 'RULE' THEN 'RULE'
                ELSE excluded.classified_by
            END
        """,
        [(r.vote_id, r.impact_tag, r.confidence, r.classified_by) for r in rows],
    )
    return len(rows)


def _append_review_queue(rows: list[dict[str, Any]]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not REVIEW_QUEUE_PATH.exists()
    with REVIEW_QUEUE_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "vote_id",
                "impact_tag",
                "confidence",
                "classified_by",
                "vote_question",
                "title",
                "queued_at_utc",
                "human_decision",
            ],
        )
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def fetch_votes_for_classification(
    conn,
    *,
    new_only: bool = False,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            v.vote_id,
            v.vote_category,
            v.vote_question,
            b.title,
            b.short_title,
            b.policy_area
        FROM fact_vote v
        LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
    """
    if new_only:
        sql += """
        WHERE NOT EXISTS (
            SELECT 1 FROM bridge_vote_impact i WHERE i.vote_id = v.vote_id
        )
        """
    rows = conn.execute(sql).fetchall()
    cols = [
        "vote_id",
        "vote_category",
        "vote_question",
        "title",
        "short_title",
        "policy_area",
    ]
    return [dict(zip(cols, r)) for r in rows]


def classify_corpus(
    *,
    new_only: bool = False,
    enable_llm: bool = True,
    warehouse_path: Path | None = None,
    rulebook_path: Path | None = None,
) -> dict[str, int]:
    """Run Stage-1 rules (and optional Stage-2 LLM) over fact_vote."""
    rulebook = load_rulebook(rulebook_path)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        votes = fetch_votes_for_classification(conn, new_only=new_only)
        rule_rows: list[Classification] = []
        llm_written = 0
        queued = 0
        excluded = 0

        for vote in votes:
            if vote["vote_category"] in rulebook.exclude_categories:
                excluded += 1
                continue
            hits = classify_rules(
                vote_id=vote["vote_id"],
                vote_category=vote["vote_category"],
                vote_question=vote["vote_question"],
                title=vote["title"],
                short_title=vote["short_title"],
                policy_area=vote["policy_area"],
                rulebook=rulebook,
            )
            if hits:
                rule_rows.extend(hits)
                continue

            text = _corpus_text(
                vote["vote_question"],
                vote["title"],
                vote["short_title"],
                vote["policy_area"],
            )
            if not enable_llm or not is_llm_eligible(text, rulebook):
                continue

            llm_hits = _llm_classify(vote_id=vote["vote_id"], text=text)
            strong = [h for h in llm_hits if h.confidence >= 0.8]
            weak = [h for h in llm_hits if h.confidence < 0.8]
            if strong:
                _upsert_bridge(conn, strong)
                llm_written += len(strong)
            if weak:
                now = datetime.now(UTC).isoformat()
                _append_review_queue(
                    [
                        {
                            "vote_id": h.vote_id,
                            "impact_tag": h.impact_tag,
                            "confidence": h.confidence,
                            "classified_by": "LLM",
                            "vote_question": vote["vote_question"],
                            "title": vote["title"],
                            "queued_at_utc": now,
                            "human_decision": "",
                        }
                        for h in weak
                    ]
                )
                queued += len(weak)

        written = _upsert_bridge(conn, rule_rows)
        return {
            "votes_scanned": len(votes),
            "excluded_personnel": excluded,
            "rule_tags_written": written,
            "llm_tags_written": llm_written,
            "review_queue_rows": queued,
        }
    finally:
        conn.close()


def promote_review_queue(
    *,
    queue_path: Path | None = None,
    warehouse_path: Path | None = None,
) -> int:
    """
    Read human-adjudicated review_queue.csv and write HUMAN classifications.

    Rows with human_decision blank / REJECT / SKIP / NO are ignored.
    ACCEPT keeps the row's impact_tag; a tag name promotes that tag.
    """
    path = queue_path or REVIEW_QUEUE_PATH
    if not path.exists():
        return 0
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        promoted: list[Classification] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                decision = (row.get("human_decision") or "").strip()
                if not decision or decision.upper() in {"REJECT", "SKIP", "NO"}:
                    continue
                if decision.upper() in {"ACCEPT", "YES"}:
                    tag = row["impact_tag"]
                elif decision.upper() in IMPACT_TAGS:
                    tag = decision.upper()
                else:
                    raise ValueError(
                        f"invalid human_decision for {row.get('vote_id')}: {decision!r}"
                    )
                if tag not in IMPACT_TAGS:
                    raise ValueError(f"invalid impact_tag for {row.get('vote_id')}: {tag!r}")
                promoted.append(
                    Classification(
                        vote_id=row["vote_id"],
                        impact_tag=tag,
                        confidence=1.0,
                        classified_by="HUMAN",
                    )
                )
        return _upsert_bridge(conn, promoted)
    finally:
        conn.close()


def list_summaries_pending(*, warehouse_path: Path | None = None) -> list[dict[str, Any]]:
    """Tagged votes whose bills lack a plain_language_summary."""
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT
                v.vote_id,
                v.vote_date,
                v.vote_category,
                v.bill_id,
                b.title,
                list(i.impact_tag ORDER BY i.impact_tag) AS tags
            FROM fact_vote v
            INNER JOIN bridge_vote_impact i ON i.vote_id = v.vote_id
            LEFT JOIN dim_bill b ON b.bill_id = v.bill_id
            WHERE v.bill_id IS NOT NULL
              AND (b.plain_language_summary IS NULL OR b.plain_language_summary = '')
            GROUP BY 1, 2, 3, 4, 5
            ORDER BY v.vote_date DESC, v.vote_id
            """
        ).fetchall()
        return [
            {
                "vote_id": r[0],
                "vote_date": r[1],
                "vote_category": r[2],
                "bill_id": r[3],
                "title": r[4],
                "tags": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()


def reclassify_all(
    *,
    confirm: bool,
    warehouse_path: Path | None = None,
    rulebook_path: Path | None = None,
) -> Path:
    """
    Full rulebook reclassify. Requires --confirm. Writes a diff before applying RULE tags.

    HUMAN labels are preserved. Non-HUMAN tags are recomputed from the rulebook.
    """
    if not confirm:
        raise RuntimeError("refusing to reclassify without --confirm")

    rulebook = load_rulebook(rulebook_path)
    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        before = {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                "SELECT vote_id, impact_tag, classified_by FROM bridge_vote_impact"
            ).fetchall()
        }
        votes = fetch_votes_for_classification(conn, new_only=False)
        desired: dict[tuple[str, str], Classification] = {}
        for vote in votes:
            for hit in classify_rules(
                vote_id=vote["vote_id"],
                vote_category=vote["vote_category"],
                vote_question=vote["vote_question"],
                title=vote["title"],
                short_title=vote["short_title"],
                policy_area=vote["policy_area"],
                rulebook=rulebook,
            ):
                desired[(hit.vote_id, hit.impact_tag)] = hit

        humans = {k for k, src in before.items() if src == "HUMAN"}

        added = sorted(set(desired) - set(before))
        removed = sorted(k for k in before if k not in desired and k not in humans)
        retained_human_only = sorted(humans - set(desired))

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Reclassify diff",
            "",
            f"Generated at {datetime.now(UTC).isoformat()}",
            f"Rulebook version: {rulebook.version}",
            "",
            f"- added RULE tags: {len(added)}",
            f"- removed non-HUMAN tags: {len(removed)}",
            f"- HUMAN tags retained without RULE match: {len(retained_human_only)}",
            f"- HUMAN tags preserved: {len(humans)}",
            "",
            "## Added",
            "",
        ]
        lines += [f"- {vid} · {tag}" for vid, tag in added] or ["- _(none)_"]
        lines += ["", "## Removed", ""]
        lines += [
            f"- {vid} · {tag} ({before[(vid, tag)]})" for vid, tag in removed
        ] or ["- _(none)_"]
        lines += ["", "## HUMAN retained (no RULE match)", ""]
        lines += [f"- {vid} · {tag}" for vid, tag in retained_human_only] or [
            "- _(none)_"
        ]
        RECLASSIFY_DIFF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Diff is on disk before mutating the bridge.
        conn.execute(
            """
            DELETE FROM bridge_vote_impact
            WHERE classified_by != 'HUMAN'
            """
        )
        _upsert_bridge(conn, list(desired.values()))
        return RECLASSIFY_DIFF_PATH
    finally:
        conn.close()
