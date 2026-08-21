"""Senate seat model (`senate-v0.1`).

Fitted forecast: state presidential lean, incumbency, the midterm dummy, a
frozen uniform national swing, and a poll blend. Pre-registered in
SENATE_MODEL_SPEC.md.

Deliberately short on features. At ~244 races across eight cycles, with races
inside a cycle sharing the national environment, the effective sample cannot
support the feature count the House model carries — and the House model's own
`qual_dem` failure is a live demonstration of what a weakly-identified feature
does to published numbers. Anything richer has to beat this on leave-one-cycle-
out Brier before it ships.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import yaml
from scipy.stats import norm

from vact.analysis.races import Chamber, RaceRegistry, load_races, race_label
from vact.analysis.seat_model import (
    ENV_MARGIN_MAX,
    ENV_MARGIN_MIN,
    ENV_MARGIN_STEP,
    Z_80,
    env_margin_grid,
    flip_threshold_pp,
    generic_to_margin_pp,
    latest_generic_ballot,
    margin_pp_to_nat_env,
    poll_average,
    prior_presidential_year,
)
from vact.analysis.senate_train import (
    TRAIN_PATH,
    load_national_presidential,
    load_state_presidential,
)
from vact.paths import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "config" / "senate_model.yaml"
FIT_PATH = REPO_ROOT / "data" / "derived" / "senate_model_fit.json"
# midterm_dem is deliberately absent: nat_env already carries the cycle's
# national environment, so the dummy is constant-within-cycle and adds nothing.
# Dropping it left leave-one-cycle-out Brier unchanged at 0.0885.
OLS_FEATURES = ("intercept", "lean_rel_dem", "inc_dem")


class SenateModelError(ValueError):
    """Spec, fit, or registry failure."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def load_training(path: Path | None = None) -> list[dict[str, Any]]:
    dest = path or TRAIN_PATH
    if not dest.is_file():
        raise SenateModelError(f"senate training extract missing: {dest}")
    with dest.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SenateModelError(f"{dest} is empty")
    return rows


def design(rows: Iterable[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """X (without nat_env), y, and the nat_env offset column."""
    xs, ys, envs = [], [], []
    for r in rows:
        xs.append([1.0, float(r["lean_rel_dem"]), float(r["inc_dem"])])
        ys.append(float(r["dem_two_party"]))
        envs.append(float(r["nat_env"]))
    return np.array(xs, dtype=float), np.array(ys, dtype=float), np.array(envs, dtype=float)


def _fit_ols(rows: list[dict[str, Any]]) -> tuple[np.ndarray, float]:
    x, y, env = design(rows)
    # nat_env enters with a frozen coefficient of 1.0 (collinear with the midterm
    # dummy at cycle level), so it is removed from the target before fitting.
    target = y - env
    beta, *_ = np.linalg.lstsq(x, target, rcond=None)
    resid = target - x @ beta
    sigma = float(np.sqrt(np.mean(resid**2)))
    return beta, sigma


def _brier(probs: Iterable[float], outcomes: Iterable[bool]) -> float:
    p = list(probs)
    o = list(outcomes)
    return float(np.mean([(pi - (1.0 if oi else 0.0)) ** 2 for pi, oi in zip(p, o)]))


def leave_one_cycle_out(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Refit without each cycle and score that cycle. A single 33-race holdout
    cannot separate these models; eight folds can at least rank them."""
    years = sorted({int(r["year"]) for r in rows})
    model_p: list[float] = []
    lean_p: list[float] = []
    inc_p: list[float] = []
    truth: list[bool] = []
    per_cycle: list[dict[str, Any]] = []

    for year in years:
        train = [r for r in rows if int(r["year"]) != year]
        test = [r for r in rows if int(r["year"]) == year]
        beta, sigma = _fit_ols(train)
        # lean + uniform swing only: incumbency zeroed out
        lean_rows = [{**r, "inc_dem": 0} for r in train]
        beta_l, sigma_l = _fit_ols(lean_rows)

        x, y, env = design(test)
        mu = x @ beta + env
        p = norm.cdf((mu - 0.5) / sigma)

        xl, _yl, envl = design([{**r, "inc_dem": 0} for r in test])
        mul = xl @ beta_l + envl
        pl = norm.cdf((mul - 0.5) / sigma_l)

        outcomes = [r["dem_winner"] in (True, "True", "true", "1") for r in test]
        pi = [
            1.0 if int(r["inc_dem"]) == 1 else 0.0 if int(r["inc_dem"]) == -1 else 0.5
            for r in test
        ]
        model_p.extend(p.tolist()); lean_p.extend(pl.tolist()); inc_p.extend(pi)
        truth.extend(outcomes)
        per_cycle.append({
            "year": year,
            "n": len(test),
            "brier_model": round(_brier(p.tolist(), outcomes), 4),
            "brier_lean_swing": round(_brier(pl.tolist(), outcomes), 4),
            "brier_always_incumbent": round(_brier(pi, outcomes), 4),
        })

    return {
        "scheme": "leave_one_cycle_out",
        "n": len(truth),
        "brier_model": round(_brier(model_p, truth), 4),
        "brier_lean_swing": round(_brier(lean_p, truth), 4),
        "brier_always_incumbent": round(_brier(inc_p, truth), 4),
        "per_cycle": per_cycle,
    }


def fit(*, config: dict[str, Any] | None = None, dest: Path | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    rows = load_training()
    beta, sigma = _fit_ols(rows)
    cv = leave_one_cycle_out(rows)
    summary = {
        "model_version": cfg["model_version"],
        "n_train": len(rows),
        "cycles": sorted({int(r["year"]) for r in rows}),
        "features": list(OLS_FEATURES),
        "ols_beta": {n: float(v) for n, v in zip(OLS_FEATURES, beta)},
        "nat_env_beta": 1.0,
        "sigma": sigma,
        "cv": cv,
    }
    path = dest or FIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def load_fit(path: Path | None = None) -> dict[str, Any]:
    dest = path or FIT_PATH
    if not dest.is_file():
        raise SenateModelError(f"senate fit missing: {dest}. Run `vact senate fit`.")
    return json.loads(dest.read_text(encoding="utf-8"))


def _plain_language(p_dem: float) -> str:
    if p_dem >= 0.95:
        return "Democrats are overwhelming favorites"
    if p_dem >= 0.80:
        return "Democrats are clear favorites"
    if p_dem >= 0.60:
        return "Democrats are modest favorites"
    if p_dem > 0.40:
        return "The race is a toss-up"
    if p_dem > 0.20:
        return "Republicans are modest favorites"
    if p_dem > 0.05:
        return "Republicans are clear favorites"
    return "Republicans are overwhelming favorites"


def takeaway_sentence(label: str, margins, probs) -> str:
    thr = flip_threshold_pp(margins, probs)
    lo, hi = float(margins[0]), float(margins[-1])
    if thr is None:
        return (
            f"{label} stays below 50% Democratic win probability even if the "
            f"national environment reaches D{hi:+g}."
        )
    if thr <= lo:
        return (
            f"{label} stays above 50% Democratic win probability even if the "
            f"national environment reaches D{lo:+g}."
        )
    return (
        f"{label} crosses 50% Democratic win probability if the national "
        f"environment reaches D{thr:+g}."
    )


def _state_lean(race, cfg: dict[str, Any]) -> tuple[float, str]:
    """Presidential lean relative to the nation, same construct as training."""
    lean_year = prior_presidential_year(int(cfg["cycle"]))
    share = race.district_lean.pres_2024_two_party_dem_share
    label = "pres_2024"
    if share is None:
        share = race.district_lean.pres_2020_two_party_dem_share
        label = "pres_2020"
        lean_year = 2020
    if share is None:
        return 0.0, "missing_zeroed"
    nat = load_national_presidential().get(lean_year)
    if nat is None:
        return 0.0, "missing_zeroed"
    value = float(share)
    if value > 1.5:
        value /= 100.0
    return value - nat, label


def predict(
    *,
    as_of: date | None = None,
    registry: RaceRegistry | None = None,
    config: dict[str, Any] | None = None,
    fit_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    day = as_of or date.today()
    doc = fit_doc or load_fit()
    if doc["model_version"] != cfg["model_version"]:
        raise SenateModelError(
            f"fit version {doc['model_version']} != config {cfg['model_version']}"
        )
    beta = np.array([doc["ols_beta"][n] for n in OLS_FEATURES], dtype=float)
    sigma = float(doc["sigma"])
    reg = registry or load_races()
    generic = latest_generic_ballot(as_of=day)
    default_margin = round(generic_to_margin_pp(generic) / ENV_MARGIN_STEP) * ENV_MARGIN_STEP
    default_margin = float(max(ENV_MARGIN_MIN, min(ENV_MARGIN_MAX, default_margin)))
    margins = env_margin_grid()

    races_out = []
    grid_probs: dict[str, list[float]] = {}
    for race in reg.races:
        if race.chamber is not Chamber.SENATE or race.status.value != "tracked":
            continue
        lean_rel, lean_status = _state_lean(race, cfg)
        inc_dem = 1 if race.incumbent.party == "Democrat" else -1
        x = np.array([1.0, lean_rel, float(inc_dem)], dtype=float)
        mu_ols = float(x @ beta)
        poll = poll_average(
            race.race_id, as_of=day, half_life_days=float(cfg["poll_half_life_days"])
        )
        probs, mus = [], []
        for margin in margins:
            mu_e = mu_ols + margin_pp_to_nat_env(margin)
            if poll is not None:
                w_f = 1.0 / (sigma**2)
                w_p = 1.0 / max(poll["sigma"] ** 2, 1e-6) if "sigma" in poll else 0.0
                mu_e = (w_f * mu_e + w_p * poll["dem_two_party"]) / (w_f + w_p) if w_p else mu_e
            probs.append(round(float(norm.cdf((mu_e - 0.5) / sigma)), 4))
            mus.append(round(mu_e, 4))
        grid_probs[race.race_id] = probs

        mu = mu_ols + margin_pp_to_nat_env(default_margin)
        p_dem = float(norm.cdf((mu - 0.5) / sigma))
        parts = {"intercept": float(beta[0])}
        for name, value, b in zip(OLS_FEATURES[1:], x[1:], beta[1:]):
            parts[name] = float(b * value)
        parts["nat_env"] = margin_pp_to_nat_env(default_margin)
        races_out.append({
            "race_id": race.race_id,
            "state_po": "VA",
            "as_of": day.isoformat(),
            "model_version": cfg["model_version"],
            "prob_dem": round(p_dem, 4),
            "prob_rep": round(1.0 - p_dem, 4),
            "mu_dem_two_party": round(mu, 4),
            "mu_fundamentals": round(mu, 4),
            "share_lo": round(max(0.0, mu - Z_80 * sigma), 4),
            "share_hi": round(min(1.0, mu + Z_80 * sigma), 4),
            "sigma": round(sigma, 4),
            "blend": "fundamentals_only" if poll is None else "fundamentals_plus_polls",
            "plain_language": _plain_language(p_dem),
            "takeaway": takeaway_sentence(race_label(race), margins, probs),
            "flip_threshold_pp": flip_threshold_pp(margins, probs),
            "n_polls": 0 if poll is None else poll["n_polls"],
            "decomposition": {k: round(v, 4) for k, v in parts.items()},
            "meta": {
                "lean_status": lean_status,
                "lean_rel_dem": round(lean_rel, 4),
                "environment_source": "generic_ballot" if generic else "neutral_default",
            },
            "env_probs": probs,
            "env_mu": mus,
        })

    return {
        "model_version": cfg["model_version"],
        "as_of": day.isoformat(),
        "sigma_fundamentals": sigma,
        "generic_ballot": generic,
        "env_grid": {
            "margin_pp": margins,
            "unit": "democratic_generic_ballot_margin_points",
            "step": ENV_MARGIN_STEP,
            "min": ENV_MARGIN_MIN,
            "max": ENV_MARGIN_MAX,
            "default_margin_pp": default_margin,
            "probs": grid_probs,
        },
        "races": races_out,
        "fit": {
            "n_train": doc["n_train"],
            "cycles": doc["cycles"],
            "cv": doc["cv"],
        },
    }
