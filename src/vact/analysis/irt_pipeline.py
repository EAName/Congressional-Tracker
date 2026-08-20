"""Bayesian 2PL IRT for member ideal points (Prompt 4).

Offline only. NUTS never runs on Vercel or inside `vact export-web`.

    P(yea_ij) = logistic(gamma_j * (theta_i - b_j))

Priors match the kit: theta ~ N(0,1), b ~ N(0,2), gamma ~ N(0,2).
Identification is a per-draw sign flip so theta[high] >= theta[low] for the
config bioguide anchors. Scale stays on the N(0,1) prior; we do not pin
numeric values on the anchors (that would fight the prior and inflate R-hat).

Input is contested YEA/NAY in votes.csv, one row per (member, rollcall) after
theme-dedup. axis_direction is unused in the likelihood.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from vact.analysis.votes import VoteCast, VoteRow, validate_votes_csv
from vact.paths import REPO_ROOT

IRT_CONFIG_PATH = REPO_ROOT / "config" / "irt.yaml"
IRT_OUT_PATH = REPO_ROOT / "data" / "derived" / "irt.json"


class IrtConvergenceError(RuntimeError):
    """R-hat or ESS gate failed. Do not publish the artifact."""


class IrtConfigError(ValueError):
    """Anchors missing from the filtered matrix, or config is unusable."""


@dataclass(frozen=True)
class IrtConfig:
    low_anchor: str
    high_anchor: str
    draws: int
    tune: int
    chains: int
    target_accept: float
    seed: int
    rhat_max: float
    ess_bulk_min: float
    hdi_prob: float
    min_member_votes: int
    min_item_voters: int
    drop_unanimous: bool


@dataclass(frozen=True)
class ResponseMatrix:
    member_ids: tuple[str, ...]
    item_ids: tuple[str, ...]
    member_idx: np.ndarray
    item_idx: np.ndarray
    y: np.ndarray
    members: tuple[dict[str, Any], ...]
    items: tuple[dict[str, Any], ...]

    @property
    def n_members(self) -> int:
        return len(self.member_ids)

    @property
    def n_items(self) -> int:
        return len(self.item_ids)


def load_irt_config(path: Path | None = None) -> IrtConfig:
    payload = yaml.safe_load((path or IRT_CONFIG_PATH).read_text(encoding="utf-8")) or {}
    anchors = payload.get("anchors") or {}
    sample = payload.get("sample") or {}
    gates = payload.get("gates") or {}
    filt = payload.get("filter") or {}
    low = str(anchors.get("low") or "").strip()
    high = str(anchors.get("high") or "").strip()
    if not low or not high:
        raise IrtConfigError("config/irt.yaml must set anchors.low and anchors.high as bioguide_id")
    if low == high:
        raise IrtConfigError("anchors.low and anchors.high must be distinct bioguide_ids")
    chains = int(sample.get("chains") or 4)
    if chains != 4:
        raise IrtConfigError("sample.chains must be 4 (kit NUTS contract)")
    return IrtConfig(
        low_anchor=low,
        high_anchor=high,
        draws=int(sample.get("draws") or 1000),
        tune=int(sample.get("tune") or 1000),
        chains=chains,
        target_accept=float(sample.get("target_accept") or 0.9),
        seed=int(sample.get("seed") or 42),
        rhat_max=float(gates.get("rhat_max") or 1.01),
        ess_bulk_min=float(gates.get("ess_bulk_min") or 200),
        hdi_prob=float(gates.get("hdi_prob") or 0.95),
        min_member_votes=int(filt.get("min_member_votes") or 3),
        min_item_voters=int(filt.get("min_item_voters") or 3),
        drop_unanimous=bool(filt.get("drop_unanimous", True)),
    )


def build_response_matrix(
    rows: Sequence[VoteRow],
    config: IrtConfig,
) -> ResponseMatrix:
    """Contested YEA/NAY, one observation per (member, rollcall)."""
    seen: dict[tuple[str, str], int] = {}
    raw: list[tuple[str, str, int, VoteRow]] = []
    item_themes: dict[str, list[str]] = {}
    for row in rows:
        if row.vote_cast not in {VoteCast.YEA, VoteCast.NAY}:
            continue
        themes = item_themes.setdefault(row.rollcall_id, [])
        if row.theme not in themes:
            themes.append(row.theme)
        key = (row.member_bioguide_id, row.rollcall_id)
        if key in seen:
            continue
        seen[key] = 1
        y = 1 if row.vote_cast is VoteCast.YEA else 0
        raw.append((row.member_bioguide_id, row.rollcall_id, y, row))

    by_member: dict[str, int] = {}
    by_item: dict[str, list[int]] = {}
    for bio, vote_id, y, _ in raw:
        by_member[bio] = by_member.get(bio, 0) + 1
        by_item.setdefault(vote_id, []).append(y)

    keep_members = {bio for bio, n in by_member.items() if n >= config.min_member_votes}
    keep_items: set[str] = set()
    for vote_id, ys in by_item.items():
        if len(ys) < config.min_item_voters:
            continue
        if config.drop_unanimous and (all(v == 1 for v in ys) or all(v == 0 for v in ys)):
            continue
        keep_items.add(vote_id)

    kept = [t for t in raw if t[0] in keep_members and t[1] in keep_items]
    if not kept:
        raise IrtConfigError("no IRT observations after filters")

    member_ids = tuple(sorted({t[0] for t in kept}))
    item_ids = tuple(sorted({t[1] for t in kept}))
    m_index = {b: i for i, b in enumerate(member_ids)}
    j_index = {v: i for i, v in enumerate(item_ids)}

    member_meta: dict[str, dict[str, Any]] = {}
    item_meta: dict[str, dict[str, Any]] = {}
    for bio, vote_id, y, row in kept:
        if bio not in member_meta:
            member_meta[bio] = {
                "bioguide_id": bio,
                "full_name": row.member_name,
                "party": row.party or None,
                "chamber": row.chamber,
                "district_number": row.district_number,
            }
        item_meta.setdefault(
            vote_id,
            {
                "vote_id": vote_id,
                "bill_id": row.bill_id or None,
                "date": row.rollcall_date,
                "themes": list(item_themes.get(vote_id, [])),
                "source_url": row.source_url,
            },
        )

    member_idx = np.array([m_index[t[0]] for t in kept], dtype=np.int32)
    item_idx = np.array([j_index[t[1]] for t in kept], dtype=np.int32)
    y = np.array([t[2] for t in kept], dtype=np.int8)
    members = tuple(member_meta[b] for b in member_ids)
    items = tuple(item_meta[v] for v in item_ids)
    return ResponseMatrix(
        member_ids=member_ids,
        item_ids=item_ids,
        member_idx=member_idx,
        item_idx=item_idx,
        y=y,
        members=members,
        items=items,
    )


def apply_anchor_sign(
    theta: np.ndarray,
    b: np.ndarray,
    gamma: np.ndarray,
    i_low: int,
    i_high: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flip draws where the high anchor sits left of the low anchor.

    theta, b, gamma are (n_draw, n_par). Sign is applied per draw so the
    posterior is not a 50/50 mixture around zero.
    """
    if theta.ndim != 2 or b.ndim != 2 or gamma.ndim != 2:
        raise ValueError("theta, b, gamma must be (n_draw, n_par)")
    flip = theta[:, i_high] < theta[:, i_low]
    sign = np.where(flip, -1.0, 1.0)[:, None]
    return theta * sign, b * sign, gamma * sign


def _stack_draws(da) -> np.ndarray:
    """(chain, draw, par) -> (chain * draw, par)."""
    values = np.asarray(da.values)
    if values.ndim != 3:
        raise ValueError(f"expected 3D posterior, got {values.shape}")
    return values.reshape(values.shape[0] * values.shape[1], values.shape[2])


def identify_inference_data(idata: Any, i_low: int, i_high: int) -> Any:
    import xarray as xr

    theta = idata.posterior["theta"]
    sign = xr.where(
        theta.isel(member=i_high) >= theta.isel(member=i_low),
        1.0,
        -1.0,
    )
    idata.posterior["theta"] = theta * sign
    idata.posterior["b"] = idata.posterior["b"] * sign
    idata.posterior["gamma"] = idata.posterior["gamma"] * sign
    return idata


def _assert_gates(idata: Any, config: IrtConfig) -> dict[str, float]:
    import arviz as az

    rhat = az.rhat(idata, var_names=["theta", "b", "gamma"])
    ess = az.ess(idata, var_names=["theta"], method="bulk")
    rhat_max = float(max(np.nanmax(np.asarray(rhat[v].values)) for v in rhat.data_vars))
    ess_min = float(np.nanmin(np.asarray(ess["theta"].values)))
    diag = {
        "rhat_max": round(rhat_max, 4),
        "ess_bulk_min_theta": round(ess_min, 1),
        "n_draws": int(idata.posterior.sizes.get("draw", 0)),
        "n_chains": int(idata.posterior.sizes.get("chain", 0)),
    }
    if rhat_max >= config.rhat_max:
        raise IrtConvergenceError(
            f"R-hat {rhat_max:.4f} >= {config.rhat_max}; refusing to write irt.json"
        )
    if ess_min < config.ess_bulk_min:
        raise IrtConvergenceError(
            f"ESS bulk min {ess_min:.1f} < {config.ess_bulk_min}; refusing to write irt.json"
        )
    return diag


def fit_2pl(
    matrix: ResponseMatrix,
    config: IrtConfig,
    *,
    draws: int | None = None,
    tune: int | None = None,
    seed: int | None = None,
    progressbar: bool = False,
) -> Any:
    """NUTS 4-chain 2PL. Returns identified InferenceData."""
    import pymc as pm

    if config.low_anchor not in matrix.member_ids:
        raise IrtConfigError(f"anchor low {config.low_anchor} not in filtered member set")
    if config.high_anchor not in matrix.member_ids:
        raise IrtConfigError(f"anchor high {config.high_anchor} not in filtered member set")
    i_low = matrix.member_ids.index(config.low_anchor)
    i_high = matrix.member_ids.index(config.high_anchor)

    coords = {"member": list(matrix.member_ids), "item": list(matrix.item_ids)}
    n_draws = config.draws if draws is None else draws
    n_tune = config.tune if tune is None else tune
    rng_seed = config.seed if seed is None else seed

    with pm.Model(coords=coords):
        theta = pm.Normal("theta", 0.0, 1.0, dims="member")
        b = pm.Normal("b", 0.0, 2.0, dims="item")
        gamma = pm.Normal("gamma", 0.0, 2.0, dims="item")
        eta = gamma[matrix.item_idx] * (theta[matrix.member_idx] - b[matrix.item_idx])
        pm.Bernoulli("y", logit_p=eta, observed=matrix.y)
        idata = pm.sample(
            draws=n_draws,
            tune=n_tune,
            chains=config.chains,
            target_accept=config.target_accept,
            random_seed=rng_seed,
            progressbar=progressbar,
            idata_kwargs={"log_likelihood": False},
        )
    return identify_inference_data(idata, i_low, i_high)


def _hdi_1d(samples: np.ndarray, prob: float) -> tuple[float, float]:
    import arviz as az

    interval = az.hdi(samples, hdi_prob=prob)
    return float(interval[0]), float(interval[1])


def posterior_summary(
    idata: Any,
    matrix: ResponseMatrix,
    config: IrtConfig,
    *,
    votes_commit: str | None,
    fitted_at_utc: str,
) -> dict[str, Any]:
    diag = _assert_gates(idata, config)
    theta = _stack_draws(idata.posterior["theta"])
    b = _stack_draws(idata.posterior["b"])
    gamma = _stack_draws(idata.posterior["gamma"])
    members_out: list[dict[str, Any]] = []
    for i, meta in enumerate(matrix.members):
        col = theta[:, i]
        lo, hi = _hdi_1d(col, config.hdi_prob)
        members_out.append(
            {
                **meta,
                "theta_mean": round(float(col.mean()), 4),
                "theta_hdi_lo": round(lo, 4),
                "theta_hdi_hi": round(hi, 4),
                "is_anchor_low": meta["bioguide_id"] == config.low_anchor,
                "is_anchor_high": meta["bioguide_id"] == config.high_anchor,
            }
        )
    votes_out: list[dict[str, Any]] = []
    abs_gamma: list[float] = []
    for j, meta in enumerate(matrix.items):
        g = gamma[:, j]
        glo, ghi = _hdi_1d(g, config.hdi_prob)
        blo, bhi = _hdi_1d(b[:, j], config.hdi_prob)
        g_mean = float(g.mean())
        abs_gamma.append(abs(g_mean))
        votes_out.append(
            {
                **meta,
                "b_mean": round(float(b[:, j].mean()), 4),
                "b_hdi_lo": round(blo, 4),
                "b_hdi_hi": round(bhi, 4),
                "gamma_mean": round(g_mean, 4),
                "gamma_hdi": [round(glo, 4), round(ghi, 4)],
                "gamma_hdi_lo": round(glo, 4),
                "gamma_hdi_hi": round(ghi, 4),
            }
        )
    members_out.sort(key=lambda r: r["theta_mean"])
    gamma_median = float(np.median(abs_gamma)) if abs_gamma else 0.0
    return {
        "model": "2pl",
        "formula": "P(yea_ij) = logistic(gamma_j * (theta_i - b_j))",
        "priors": {"theta": "Normal(0,1)", "b": "Normal(0,2)", "gamma": "Normal(0,2)"},
        "identification": {
            "method": "per_draw_sign_flip",
            "low_anchor": config.low_anchor,
            "high_anchor": config.high_anchor,
            "rule": "theta[high] >= theta[low] on every draw",
        },
        "diagnostics": diag,
        "hdi_prob": config.hdi_prob,
        "gamma_median_abs": round(gamma_median, 4),
        "votes_csv_commit": votes_commit,
        "fitted_at_utc": fitted_at_utc,
        "n_obs": int(matrix.y.size),
        "n_members": matrix.n_members,
        "n_items": matrix.n_items,
        "members": members_out,
        "votes": votes_out,
        "rhat_max": diag["rhat_max"],
        "ess_bulk_min": diag["ess_bulk_min_theta"],
    }


def votes_csv_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "data/votes.csv"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def write_irt_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_irt(
    *,
    votes_path: Path | None = None,
    config_path: Path | None = None,
    out_path: Path | None = None,
    copy_web: bool = True,
    draws: int | None = None,
    tune: int | None = None,
    seed: int | None = None,
    progressbar: bool = False,
) -> dict[str, Any]:
    cfg = load_irt_config(config_path)
    rows = validate_votes_csv(votes_path)
    matrix = build_response_matrix(rows, cfg)
    idata = fit_2pl(matrix, cfg, draws=draws, tune=tune, seed=seed, progressbar=progressbar)
    fitted_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = posterior_summary(
        idata,
        matrix,
        cfg,
        votes_commit=votes_csv_commit(),
        fitted_at_utc=fitted_at,
    )
    dest = out_path or IRT_OUT_PATH
    write_irt_json(payload, dest)
    if copy_web:
        from vact.exports.web import WEB_DATA_DIR

        write_irt_json(payload, WEB_DATA_DIR / "irt.json")
    return payload
