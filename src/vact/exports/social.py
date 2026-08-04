"""1200×675 social cards (Pillow) for district pages."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from vact.exports.data import district_votes_for_member, generated_at_utc, target_four
from vact.paths import REPO_ROOT
from vact.warehouse.connection import connect, ensure_schema

DEFAULT_OUT = REPO_ROOT / "docs" / "social"
WIDTH, HEIGHT = 1200, 675


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    # Prefer system fonts that render cleanly on macOS/Linux CI.
    candidates = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_card(
    *,
    member_name: str,
    district_number: int,
    summary: str,
    position: str,
    source_url: str,
    generated_at: str,
    out_path: Path,
) -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), color=(244, 247, 251))
    draw = ImageDraw.Draw(img)

    # Atmosphere band
    draw.rectangle((0, 0, WIDTH, 150), fill=(20, 58, 92))
    draw.rectangle((0, 150, WIDTH, 156), fill=(196, 92, 38))

    brand = _font(28, bold=True)
    title = _font(46, bold=True)
    body = _font(30)
    small = _font(22)
    pos_font = _font(36, bold=True)

    draw.text((48, 40), "Democrats for Virginia", fill=(255, 255, 255), font=brand)
    draw.text(
        (48, 84),
        f"VA-{district_number} · {member_name}",
        fill=(230, 240, 250),
        font=small,
    )

    y = 190
    draw.text((48, y), f"Position: {position}", fill=(31, 107, 74) if position == "YEA" else (139, 41, 66), font=pos_font)
    y += 60

    for line in _wrap(draw, summary, body, WIDTH - 96)[:5]:
        draw.text((48, y), line, fill=(11, 31, 51), font=body)
        y += 40

    y = max(y + 20, 520)
    draw.text((48, y), f"Source: {source_url[:90]}", fill=(74, 96, 116), font=small)
    draw.text((48, HEIGHT - 48), f"Generated {generated_at}", fill=(74, 96, 116), font=small)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path


def build_social_cards(
    *,
    out_dir: Path | None = None,
    warehouse_path: Path | None = None,
    map_version: str = "2026",
) -> list[Path]:
    """One 1200×675 PNG per target district (latest eligible vote when available)."""
    dest = out_dir or DEFAULT_OUT
    dest.mkdir(parents=True, exist_ok=True)
    ts = generated_at_utc()
    written: list[Path] = []

    conn = connect(warehouse_path)
    try:
        ensure_schema(conn)
        for member in target_four(conn, map_version=map_version):
            district = member["district_number"]
            votes = district_votes_for_member(conn, bioguide_id=member["bioguide_id"], limit=1)
            out = dest / f"va-{district}.png"
            if not votes:
                # Placeholder card so publish pipelines still emit assets.
                render_card(
                    member_name=member["full_name"],
                    district_number=int(district),
                    summary="No publication-ready votes yet. Summaries are human-written.",
                    position="—",
                    source_url="https://clerk.house.gov / https://www.senate.gov",
                    generated_at=ts,
                    out_path=out,
                )
            else:
                vote = votes[0]
                if not vote["plain_language_summary"]:
                    raise RuntimeError(
                        f"refusing social card for {vote['vote_id']}: null summary"
                    )
                render_card(
                    member_name=member["full_name"],
                    district_number=int(district),
                    summary=str(vote["plain_language_summary"]),
                    position=str(vote["position"]),
                    source_url=str(vote["source_url"] or ""),
                    generated_at=ts,
                    out_path=out,
                )
            written.append(out)
    finally:
        conn.close()
    return written
