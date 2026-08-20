"""Methodology payload for the static /methodology page (Prompt 3).

Hyperparameters, the worked example, and the separation simulation are computed
at export time from the live scoring frame. The Next.js page must not hardcode
α, β, k, or n. Changelog is `git log` of the adjudication file and the scoring
modules.

Simulation is not persisted in DuckDB (AGENTS.md §8). It is a derived artifact,
like scores.json.
"""

from __future__ import annotations

import subprocess
from typing import Any

import numpy as np
from scipy.stats import beta as beta_dist

from vact.analysis.estimators import BetaPrior
from vact.analysis.scoring import ScoringConfig
from vact.paths import REPO_ROOT

PUBLIC_REPO = "https://github.com/EAName/Congressional-Tracker"
CHANGELOG_PATHS = (
    "data/votes.csv",
    "src/vact/analysis/scoring.py",
    "src/vact/analysis/estimators.py",
    "config/scoring.yaml",
)


def scoring_changelog(limit: int = 40) -> list[dict[str, str]]:
    """Deduplicated git history of the scoring/adjudication files."""
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                f"-{limit}",
                "--date=short",
                "--format=%h\t%ad\t%s",
                "--",
                *CHANGELOG_PATHS,
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, date, subject = parts
        if sha in seen:
            continue
        seen.add(sha)
        out.append({"sha": sha, "date": date, "subject": subject.strip()})
    return out


def pick_worked_example(scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer a sufficient cell with the largest |EB − raw| shrinkage."""
    candidates = [
        s
        for s in scores
        if s.get("sufficient")
        and s.get("raw_score") is not None
        and s.get("eb_score") is not None
        and int(s.get("n") or s.get("n_contested") or 0) > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: abs(float(s["eb_score"]) - float(s["raw_score"])))


def _example_math(row: dict[str, Any]) -> dict[str, Any]:
    k = int(row["k"])
    n = int(row["n"])
    alpha = float(row["prior_alpha"])
    beta = float(row["prior_beta"])
    post_a = alpha + k
    post_b = beta + (n - k)
    p_raw = k / n
    prior_mean = alpha / (alpha + beta)
    post_mean = post_a / (post_a + post_b)
    return {
        "bioguide_id": row["bioguide_id"],
        "full_name": row["full_name"],
        "party": row.get("party"),
        "chamber": row.get("chamber"),
        "district_number": row.get("district_number"),
        "theme": row["theme"],
        "k": k,
        "n": n,
        "p_raw": round(p_raw, 4),
        "raw_score": row["raw_score"],
        "wilson_lo": row.get("wilson_lo") or row.get("wilson_low"),
        "wilson_hi": row.get("wilson_hi") or row.get("wilson_high"),
        "prior_alpha": round(alpha, 6),
        "prior_beta": round(beta, 6),
        "prior_source": row["prior_source"],
        "prior_mean": round(prior_mean, 4),
        "post_alpha": round(post_a, 6),
        "post_beta": round(post_b, 6),
        "post_mean": round(post_mean, 4),
        "eb_score": row["eb_score"],
        "cred_lo": row["cred_lo"],
        "cred_hi": row["cred_hi"],
        "shrinkage": round(float(row["eb_score"]) - float(row["raw_score"]), 4),
    }


def n_needed_to_separate(
    *,
    delta_signed: float = 0.25,
    power: float = 0.80,
    prior: BetaPrior,
    n_sims: int = 2000,
    max_n: int = 400,
    seed: int = 42,
    cred_level: float = 0.95,
) -> dict[str, Any]:
    """Smallest equal-n where 95% credible intervals separate with given power.

    Two members have true signed scores 0 and `delta_signed` (p = 0.5 and
    0.5 + delta/2). Draws are independent binomials. 'Separate' means the
    intervals do not overlap. Failure mode: this is a power calculation under
    a known prior and known true means, not a claim about any live pair.
    """
    if delta_signed <= 0:
        raise ValueError("delta_signed must be positive")
    delta_p = delta_signed / 2.0
    p1 = 0.5
    p2 = min(0.5 + delta_p, 0.999)
    tail = (1.0 - cred_level) / 2.0
    rng = np.random.default_rng(seed)

    def power_at(n: int) -> float:
        k1 = rng.binomial(n, p1, size=n_sims)
        k2 = rng.binomial(n, p2, size=n_sims)
        a1 = prior.alpha + k1
        b1 = prior.beta + (n - k1)
        a2 = prior.alpha + k2
        b2 = prior.beta + (n - k2)
        lo1 = 2.0 * beta_dist.ppf(tail, a1, b1) - 1.0
        hi1 = 2.0 * beta_dist.ppf(1.0 - tail, a1, b1) - 1.0
        lo2 = 2.0 * beta_dist.ppf(tail, a2, b2) - 1.0
        hi2 = 2.0 * beta_dist.ppf(1.0 - tail, a2, b2) - 1.0
        separated = (hi1 < lo2) | (hi2 < lo1)
        return float(np.mean(separated))

    lo, hi = 1, max_n
    achieved: float | None = None
    n_star: int | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        pwr = power_at(mid)
        if pwr >= power:
            n_star = mid
            achieved = pwr
            hi = mid - 1
        else:
            lo = mid + 1
    power_cap = round(power_at(max_n), 3)
    return {
        "delta_signed": delta_signed,
        "power_target": power,
        "n_sims": n_sims,
        "cred_level": cred_level,
        "p_true": [p1, p2],
        "signed_true": [0.0, round(2.0 * p2 - 1.0, 4)],
        "prior_alpha": round(prior.alpha, 6),
        "prior_beta": round(prior.beta, 6),
        "prior_source": prior.source,
        "n_needed": n_star,
        "power_at_n": None if achieved is None else round(achieved, 3),
        "power_at_max_n": power_cap,
        "max_n": max_n,
        "reached": n_star is not None,
    }


def build_methodology_payload(
    config: ScoringConfig,
    scores: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    *,
    n_sims: int = 2000,
) -> dict[str, Any]:
    example_row = pick_worked_example(scores)
    example = _example_math(example_row) if example_row else None
    fallback = BetaPrior(
        alpha=config.eb_fallback_alpha,
        beta=config.eb_fallback_beta,
        source="weakly_informative",
        n_members=0,
    )
    sep_weak = n_needed_to_separate(prior=fallback, n_sims=n_sims)
    if example:
        live_prior = BetaPrior(
            alpha=float(example["prior_alpha"]),
            beta=float(example["prior_beta"]),
            source=example["prior_source"],  # type: ignore[arg-type]
            n_members=0,
        )
        sep_live = n_needed_to_separate(prior=live_prior, n_sims=n_sims)
    else:
        sep_live = None

    return {
        "repo_url": PUBLIC_REPO,
        "votes_url": f"{PUBLIC_REPO}/blob/main/data/votes.csv",
        "reproduce": [
            f"git clone {PUBLIC_REPO}.git",
            "cd Congressional-Tracker && uv sync",
            "./bin/vact votes validate && ./bin/vact export-web",
        ],
        "scoreable": {
            "axis_name": config.axis_name,
            "axis_description": config.axis_description,
            "include_categories": sorted(config.include_categories),
            "exclude_categories": sorted(config.exclude_categories),
            "exclude_rule_resolutions": config.exclude_rule_resolutions,
            "min_contested": config.min_contested,
            "wilson_z": config.wilson_z,
            "eb_method": config.eb_method,
            "eb_min_caucus": config.eb_min_caucus,
            "eb_fallback_alpha": config.eb_fallback_alpha,
            "eb_fallback_beta": config.eb_fallback_beta,
        },
        "baselines": baselines,
        "worked_example": example,
        "separation": {"weakly_informative": sep_weak, "worked_example_prior": sep_live},
        "changelog": scoring_changelog(),
    }
