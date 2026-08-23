"""Guard against the spec claiming behaviour the code does not implement.

VOTE_INCLUSION_SPEC.md is the public methodology. When it drifts from the
pipeline, the failure is not a bug report — it is "their published methodology
is not what they run." `NEAR_UNANIMOUS` was documented as an inclusion gate for
weeks while the scoring path never applied it.
"""

from __future__ import annotations

import re
from pathlib import Path

from vact.analysis.scoring import load_scoring_config
from vact.paths import REPO_ROOT

SPEC = REPO_ROOT / "src" / "vact" / "analysis" / "VOTE_INCLUSION_SPEC.md"
EXCLUDED = REPO_ROOT / "src" / "vact" / "analysis" / "excluded_votes.py"


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_every_documented_reason_code_exists_in_code() -> None:
    """A code in the spec's table must be one the pipeline can actually emit."""
    codes = set(re.findall(r"^\| `([A-Z_]+)` \|", _spec_text(), re.M))
    assert codes, "no reason codes parsed from the spec"
    src = EXCLUDED.read_text(encoding="utf-8")
    for code in codes:
        row = re.search(rf"^\| `{code}` \|(.*)$", _spec_text(), re.M)
        if row and "reserved" in row.group(1).lower():
            continue
        assert f'"{code}"' in src, f"{code} documented but never emitted"


def test_advisory_codes_are_labelled_as_such() -> None:
    """A code the scoring path does not enforce must say so, or a reader will
    assume the filter is applied."""
    text = _spec_text()
    src = EXCLUDED.read_text(encoding="utf-8")
    enforced_in_scoring = Path(REPO_ROOT / "src" / "vact" / "analysis" / "votes.py").read_text(
        encoding="utf-8"
    )
    for code in re.findall(r"^\| `([A-Z_]+)` \|(.*)$", text, re.M):
        name, desc = code
        if name not in src:
            continue
        # crude but sufficient: does the scoring path reference this filter at all?
        applied = name.lower().replace("_", "") in enforced_in_scoring.lower().replace("_", "")
        if not applied and "not enforced" not in desc.lower() and "advisory" not in desc.lower():
            # categories and valence are enforced structurally, not by code name
            if name in {"PROCEDURAL_CATEGORY", "NO_IMPACT_TAG", "UNADJUDICATED_DIRECTION", "OTHER"}:
                continue
            raise AssertionError(
                f"{name} is not applied in the scoring path and the spec does not "
                "label it advisory — the published methodology overstates the filter"
            )


def test_spec_category_list_matches_config() -> None:
    """The spec names the scoreable categories inline; config is the source of
    truth. Drift here means the methodology page lists the wrong ones."""
    text = _spec_text()
    m = re.search(r"`config/scoring\.yaml` \(currently ([^)]+)\)", text)
    assert m, "spec no longer states the scoreable categories"
    documented = {c.strip().upper() for c in m.group(1).split(",")}
    actual = {c.upper() for c in load_scoring_config().include_categories}
    assert documented == actual, f"spec says {sorted(documented)}, config has {sorted(actual)}"


def test_spec_version_matches_the_audit_config() -> None:
    import yaml

    cfg = yaml.safe_load(
        (REPO_ROOT / "config" / "symmetry_audit.yaml").read_text(encoding="utf-8")
    )
    version = cfg["inclusion_spec_version"]
    assert f"# Vote inclusion spec — `{version}`" in _spec_text(), (
        f"symmetry_audit.yaml pins {version} but the spec header disagrees"
    )
