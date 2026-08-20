"""Beta-binomial empirical Bayes estimator (Prompt 2).

Per (theme, party) we fit a Beta(α, β) prior from caucus (k, n) counts, then
the member posterior is Beta(α+k, β+n−k). The shrunk signed score is
2 · posterior mean − 1. Credible bounds are posterior quantiles on the same
signed scale.

Nothing here is persisted (AGENTS.md §8). Callers recompute from votes.csv /
the scoring frame on every export.

Failure mode if we used a single national prior: party-line structure would
pull Democrats toward Republicans (and vice versa) and erase the caucus signal
the dashboard exists to show. The (theme, party) cell is load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import betaln
from scipy.stats import beta as beta_dist

from vact.analysis.deviations import weighted_median
from vact.analysis.scoring import ScoringConfig, signed_score_from_counts

PriorSource = Literal["moments", "mle", "weakly_informative", "degenerate"]


@dataclass(frozen=True)
class BetaPrior:
    alpha: float
    beta: float
    source: PriorSource
    n_members: int

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def signed_center(self) -> float:
        return 2.0 * self.mean - 1.0


@dataclass(frozen=True)
class MemberEstimate:
    raw_score: float | None
    wilson_lo: float | None
    wilson_hi: float | None
    eb_score: float
    cred_lo: float
    cred_hi: float
    n: int
    k: int
    prior_alpha: float
    prior_beta: float
    prior_source: PriorSource
    prior_only: bool


def _to_signed(p: float) -> float:
    return round(2.0 * p - 1.0, 4)


def fit_beta_moments(ks: Sequence[int], ns: Sequence[int]) -> BetaPrior | None:
    """Method of moments on observed p_i = k_i / n_i (unweighted).

    Returns None when the sample cannot support a Beta (too few points, mean
    on the boundary, or variance too large for a Beta). Caller falls back.
    """
    pairs = [(int(k), int(n)) for k, n in zip(ks, ns, strict=True) if int(n) > 0]
    if len(pairs) < 2:
        return None
    ps = np.array([k / n for k, n in pairs], dtype=float)
    mu = float(ps.mean())
    n_members = len(pairs)
    s2 = float(ps.var(ddof=1)) if len(ps) > 1 else 0.0
    bernoulli_cap = mu * (1.0 - mu) if 0.0 < mu < 1.0 else 0.0

    if mu <= 0.0 or mu >= 1.0 or s2 <= 1e-15:
        # Unanimous / zero-variance caucus. Pool counts with a half-pseudocount
        # so concentration tracks caucus vote depth instead of a fake 1e6 peak
        # that would swallow dissenters and collapse the credible interval.
        k_sum = float(sum(k for k, _ in pairs))
        n_sum = float(sum(n for _, n in pairs))
        return BetaPrior(
            alpha=k_sum + 0.5,
            beta=(n_sum - k_sum) + 0.5,
            source="degenerate",
            n_members=n_members,
        )
    if s2 >= bernoulli_cap - 1e-15:
        return None
    concentration = bernoulli_cap / s2 - 1.0
    if concentration <= 0:
        return None
    alpha = mu * concentration
    beta = (1.0 - mu) * concentration
    if alpha <= 0 or beta <= 0:
        return None
    return BetaPrior(alpha=float(alpha), beta=float(beta), source="moments", n_members=len(pairs))


def _bb_nll(log_params: np.ndarray, ks: np.ndarray, ns: np.ndarray) -> float:
    alpha, beta = np.exp(log_params)
    if not np.isfinite(alpha) or not np.isfinite(beta) or alpha < 1e-8 or beta < 1e-8:
        return 1e12
    ll = betaln(alpha + ks, beta + ns - ks) - betaln(alpha, beta)
    return float(-np.sum(ll))


def fit_beta_mle(ks: Sequence[int], ns: Sequence[int], start: BetaPrior | None = None) -> BetaPrior | None:
    """Beta-binomial MLE on (k, n). Starts at MoM when available."""
    pairs = [(int(k), int(n)) for k, n in zip(ks, ns, strict=True) if int(n) > 0]
    if len(pairs) < 2:
        return None
    k_arr = np.array([k for k, _ in pairs], dtype=float)
    n_arr = np.array([n for _, n in pairs], dtype=float)
    seed = start or fit_beta_moments(k_arr.astype(int), n_arr.astype(int))
    if seed is None:
        x0 = np.log([2.0, 2.0])
    else:
        x0 = np.log([max(seed.alpha, 1e-3), max(seed.beta, 1e-3)])
    result = minimize(
        _bb_nll,
        x0,
        args=(k_arr, n_arr),
        method="L-BFGS-B",
        bounds=((np.log(1e-3), np.log(1e6)), (np.log(1e-3), np.log(1e6))),
    )
    if not result.success:
        return seed
    alpha, beta = np.exp(result.x)
    if not np.isfinite(alpha) or not np.isfinite(beta) or alpha <= 0 or beta <= 0:
        return seed
    return BetaPrior(alpha=float(alpha), beta=float(beta), source="mle", n_members=len(pairs))


def fit_caucus_prior(
    ks: Sequence[int],
    ns: Sequence[int],
    *,
    method: str = "moments",
    min_caucus: int = 3,
    fallback_alpha: float = 2.0,
    fallback_beta: float = 2.0,
) -> BetaPrior:
    """Fit a (theme, party) prior, or the weakly-informative fallback."""
    n_with_votes = sum(1 for n in ns if int(n) > 0)
    fallback = BetaPrior(
        alpha=fallback_alpha,
        beta=fallback_beta,
        source="weakly_informative",
        n_members=n_with_votes,
    )
    if n_with_votes < min_caucus:
        return fallback
    mom = fit_beta_moments(ks, ns)
    if method == "mle":
        mle = fit_beta_mle(ks, ns, start=mom)
        return mle or mom or fallback
    return mom or fallback


def estimate_member_theme(
    k: int,
    n: int,
    prior: BetaPrior,
    *,
    wilson_z: float = 1.96,
    cred_level: float = 0.95,
) -> MemberEstimate:
    """Posterior Beta(α+k, β+n−k). n=0 → prior only."""
    k = int(k)
    n = int(n)
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid (k, n)=({k}, {n})")
    raw = signed_score_from_counts(k, n, wilson_z)
    prior_only = n == 0
    post_a = prior.alpha + k
    post_b = prior.beta + (n - k)
    mean = post_a / (post_a + post_b)
    tail = (1.0 - cred_level) / 2.0
    lo = float(beta_dist.ppf(tail, post_a, post_b))
    hi = float(beta_dist.ppf(1.0 - tail, post_a, post_b))
    lo = min(max(lo, 0.0), 1.0)
    hi = min(max(hi, 0.0), 1.0)
    return MemberEstimate(
        raw_score=raw["signed_score"],
        wilson_lo=raw["wilson_low"],
        wilson_hi=raw["wilson_high"],
        eb_score=_to_signed(mean),
        cred_lo=_to_signed(lo),
        cred_hi=_to_signed(hi),
        n=n,
        k=k,
        prior_alpha=round(prior.alpha, 6),
        prior_beta=round(prior.beta, 6),
        prior_source=prior.source,
        prior_only=prior_only,
    )


def attach_empirical_bayes(
    frame: list[dict[str, Any]],
    config: ScoringConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Annotate each frame row with EB fields. Returns (rows, party baselines).

    Prior is fit per (impact_tag, party) from members with n_contested > 0.
    Null/empty party uses the weakly-informative fallback (no caucus).
    """
    method = config.eb_method
    min_caucus = config.eb_min_caucus
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for row in frame:
        party = row.get("party")
        if not party:
            ungrouped.append(row)
            continue
        groups.setdefault((row["impact_tag"], str(party)), []).append(row)

    priors: dict[tuple[str, str], BetaPrior] = {}
    for key, members in groups.items():
        ks = [int(m["n_pro"] or 0) for m in members]
        ns = [int(m["n_contested"] or 0) for m in members]
        priors[key] = fit_caucus_prior(
            ks,
            ns,
            method=method,
            min_caucus=min_caucus,
            fallback_alpha=config.eb_fallback_alpha,
            fallback_beta=config.eb_fallback_beta,
        )

    fallback = BetaPrior(
        alpha=config.eb_fallback_alpha,
        beta=config.eb_fallback_beta,
        source="weakly_informative",
        n_members=0,
    )

    out: list[dict[str, Any]] = []
    for row in frame:
        party = row.get("party")
        prior = priors.get((row["impact_tag"], str(party)), fallback) if party else fallback
        est = estimate_member_theme(
            int(row["n_pro"] or 0),
            int(row["n_contested"] or 0),
            prior,
            wilson_z=config.wilson_z,
        )
        rec = dict(row)
        rec.update(
            {
                "raw_score": est.raw_score,
                "wilson_lo": est.wilson_lo,
                "wilson_hi": est.wilson_hi,
                "eb_score": est.eb_score,
                "cred_lo": est.cred_lo,
                "cred_hi": est.cred_hi,
                "n": est.n,
                "k": est.k,
                "prior_alpha": est.prior_alpha,
                "prior_beta": est.prior_beta,
                "prior_source": est.prior_source,
                "prior_only": est.prior_only,
            }
        )
        out.append(rec)

    baselines: list[dict[str, Any]] = []
    for (theme, party), prior in sorted(priors.items()):
        members = [
            r
            for r in out
            if r["impact_tag"] == theme and r.get("party") == party and r["sufficient"]
            and r.get("signed_score") is not None
        ]
        pairs = [(float(r["signed_score"]), float(r["n_contested"])) for r in members]
        baselines.append(
            {
                "theme": theme,
                "party": party,
                "eb_center": round(prior.signed_center, 4),
                "weighted_median": round(weighted_median(pairs), 4) if pairs else None,
                "prior_alpha": round(prior.alpha, 6),
                "prior_beta": round(prior.beta, 6),
                "prior_source": prior.source,
                "n_members": prior.n_members,
            }
        )
    return out, baselines
