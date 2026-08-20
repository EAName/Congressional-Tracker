"""Pre-registered House seat model (Prompt 13).

Vote-share engine is OLS on Democratic two-party share. Win probability is
the normal CDF of that share so the 80% interval and the probability stay
on the same latent scale. A logit robustness fit is stored in the summary
only; it is not published.

Nothing here is stored in DuckDB (AGENTS.md §8). Coefficients live in
`data/derived/seat_model_fit.json`; published probabilities are appended to
`data/predictions_seats.csv`.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml
from scipy.optimize import minimize
from scipy.stats import norm

from vact.analysis.races import RaceRegistry, load_races
from vact.paths import DATA_DIR, REPO_ROOT
from vact.pipeline.fec import latest_snapshot

MODEL_VERSION = "seat-v1.0"
CONFIG_PATH = REPO_ROOT / "config" / "seat_model.yaml"
SPEC_PATH = REPO_ROOT / "src" / "vact" / "analysis" / "SEAT_MODEL_SPEC.md"
TRAIN_PATH = DATA_DIR / "seat_model" / "house_races_train.csv"
FIT_PATH = DATA_DIR / "derived" / "seat_model_fit.json"
GENERIC_BALLOT_PATH = DATA_DIR / "generic_ballot.csv"
DISTRICT_POLLS_PATH = DATA_DIR / "district_polls.csv"
PREDICTIONS_PATH = DATA_DIR / "predictions_seats.csv"

OLS_FEATURES = (
    "intercept",
    "lean_rel_dem",
    "inc_dem",
    "midterm_dem",
    "log_ratio_dem",
    "qual_dem",
)

Z_80 = float(norm.ppf(0.90))
DEM_PARTIES = frozenset({"DEMOCRAT", "DEMOCRATIC-FARMER-LABOR", "DEMOCRATIC FARMER LABOR"})
REP_PARTIES = frozenset({"REPUBLICAN"})
PREDICTION_FIELDS = ("race_id", "date", "prob_dem", "model_version")

# FEC certified national two-party presidential shares, used only to center CD lean.
NATIONAL_PRES_DEM = {
    "pres_2024": 48.32 / (48.32 + 49.80),
    "pres_2020": 51.31 / (51.31 + 46.85),
}


class SeatModelError(ValueError):
    """Structural failure in spec, log, or fit artifacts."""


def load_seat_config(path: Path | None = None) -> dict[str, Any]:
    dest = path or CONFIG_PATH
    return yaml.safe_load(dest.read_text(encoding="utf-8"))


def _norm_name(value: str) -> str:
    text = re.sub(r"[^A-Z0-9 ]", " ", (value or "").upper())
    parts = [p for p in text.split() if p and p not in {"JR", "SR", "II", "III", "IV"}]
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1]}"
    return parts[0] if parts else ""


def _district_key(state_po: str, district: str | int) -> str:
    raw = str(district).strip()
    if raw.upper() in {"0", "00", "000", "AL"}:
        num = 0
    else:
        num = int(raw)
    return f"{state_po.upper()}-{num:02d}"


def _party_family(party: str) -> str | None:
    p = (party or "").strip().upper()
    if p in DEM_PARTIES:
        return "Democrat"
    if p in REP_PARTIES:
        return "Republican"
    return None


def prior_presidential_year(year: int) -> int:
    """Most recent presidential election strictly before this House cycle."""
    if year % 4 == 0:
        return year - 4
    return year - (year % 4)


def _midterm_dem(year: int, president_party: str) -> int:
    if year % 4 == 0:
        return 0
    if president_party == "Democrat":
        return -1
    if president_party == "Republican":
        return 1
    raise SeatModelError(f"unknown president_party {president_party!r}")


@dataclass(frozen=True)
class RaceRow:
    year: int
    race_key: str
    state_po: str
    district: int
    dem_votes: float
    rep_votes: float
    dem_two_party: float
    dem_winner: bool
    dem_name: str
    rep_name: str
    incumbent_party: str | None
    lean_rel_dem: float
    inc_dem: int
    midterm_dem: int
    log_ratio_dem: float
    qual_dem: int
    nat_env: float
    holdout: bool


def write_training_csv(rows: Sequence[RaceRow], path: Path | None = None) -> Path:
    dest = path or TRAIN_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "year",
        "race_key",
        "state_po",
        "district",
        "dem_two_party",
        "dem_winner",
        "incumbent_party",
        "lean_rel_dem",
        "inc_dem",
        "midterm_dem",
        "log_ratio_dem",
        "qual_dem",
        "nat_env",
        "holdout",
        "dem_name",
        "rep_name",
    ]
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "year": row.year,
                    "race_key": row.race_key,
                    "state_po": row.state_po,
                    "district": row.district,
                    "dem_two_party": f"{row.dem_two_party:.6f}",
                    "dem_winner": str(row.dem_winner).lower(),
                    "incumbent_party": row.incumbent_party or "",
                    "lean_rel_dem": f"{row.lean_rel_dem:.6f}",
                    "inc_dem": row.inc_dem,
                    "midterm_dem": row.midterm_dem,
                    "log_ratio_dem": f"{row.log_ratio_dem:.6f}",
                    "qual_dem": row.qual_dem,
                    "nat_env": f"{row.nat_env:.6f}",
                    "holdout": str(row.holdout).lower(),
                    "dem_name": row.dem_name,
                    "rep_name": row.rep_name,
                }
            )
    return dest


def load_training_csv(path: Path | None = None) -> list[RaceRow]:
    dest = path or TRAIN_PATH
    if not dest.is_file():
        raise SeatModelError(f"training CSV missing: {dest}")
    rows: list[RaceRow] = []
    with dest.open(encoding="utf-8", newline="") as fh:
        for raw in csv.DictReader(fh):
            inc = raw.get("incumbent_party") or None
            rows.append(
                RaceRow(
                    year=int(raw["year"]),
                    race_key=raw["race_key"],
                    state_po=raw["state_po"],
                    district=int(raw["district"]),
                    dem_votes=0.0,
                    rep_votes=0.0,
                    dem_two_party=float(raw["dem_two_party"]),
                    dem_winner=raw["dem_winner"].lower() == "true",
                    dem_name=raw.get("dem_name") or "",
                    rep_name=raw.get("rep_name") or "",
                    incumbent_party=inc or None,
                    lean_rel_dem=float(raw["lean_rel_dem"]),
                    inc_dem=int(raw["inc_dem"]),
                    midterm_dem=int(raw["midterm_dem"]),
                    log_ratio_dem=float(raw["log_ratio_dem"]),
                    qual_dem=int(raw["qual_dem"]),
                    nat_env=float(raw["nat_env"]),
                    holdout=raw["holdout"].lower() == "true",
                )
            )
    return rows


def design_matrix(rows: Sequence[RaceRow]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.array(
        [
            [
                1.0,
                r.lean_rel_dem,
                float(r.inc_dem),
                float(r.midterm_dem),
                r.log_ratio_dem,
                float(r.qual_dem),
            ]
            for r in rows
        ],
        dtype=float,
    )
    y_share = np.array([r.dem_two_party for r in rows], dtype=float)
    y_win = np.array([1.0 if r.dem_winner else 0.0 for r in rows], dtype=float)
    return x, y_share, y_win


def fit_ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    df = max(len(y) - x.shape[1], 1)
    sigma = float(np.sqrt(np.sum(resid**2) / df))
    return beta, sigma


def fit_logit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    def nll(beta: np.ndarray) -> float:
        z = np.clip(x @ beta, -20, 20)
        p = 1.0 / (1.0 + np.exp(-z))
        p = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))

    result = minimize(nll, np.zeros(x.shape[1]), method="BFGS")
    if not result.success:
        raise SeatModelError(f"logit MLE failed: {result.message}")
    return result.x


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    if len(probs) != len(outcomes) or not probs:
        raise SeatModelError("brier requires aligned non-empty sequences")
    return float(np.mean([(p - o) ** 2 for p, o in zip(probs, outcomes, strict=True)]))


def fit_seat_model(
    rows: Sequence[RaceRow] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_seat_config()
    data = list(rows) if rows is not None else load_training_csv()
    train_years = {int(y) for y in cfg["train_years"]}
    train = [r for r in data if not r.holdout and r.year in train_years]
    hold = [r for r in data if r.holdout]
    if len(train) < 50:
        raise SeatModelError(f"training set too small: {len(train)}")
    x, y_share, y_win = design_matrix(train)
    beta, sigma = fit_ols(x, y_share)
    logit_beta = fit_logit(x, y_win)

    def probit_probs(subset: Sequence[RaceRow]) -> list[float]:
        xs, _, _ = design_matrix(subset)
        mu = xs @ beta
        return [float(norm.cdf((m - 0.5) / sigma)) for m in mu]

    train_p = probit_probs(train)
    train_y = [1 if r.dem_winner else 0 for r in train]
    hold_p = probit_probs(hold) if hold else []
    hold_y = [1 if r.dem_winner else 0 for r in hold]
    always_inc: list[float] = []
    always_inc_y: list[int] = []
    for r in hold:
        if r.incumbent_party is None:
            continue
        always_inc.append(1.0 if r.incumbent_party == "Democrat" else 0.0)
        always_inc_y.append(1 if r.dem_winner else 0)
    return {
        "model_version": cfg["model_version"],
        "fitted_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "n_train": len(train),
        "n_holdout": len(hold),
        "train_years": cfg["train_years"],
        "features": list(OLS_FEATURES),
        "ols_beta": {name: float(v) for name, v in zip(OLS_FEATURES, beta, strict=True)},
        "sigma": sigma,
        "logit_beta": {name: float(v) for name, v in zip(OLS_FEATURES, logit_beta, strict=True)},
        "nat_env_coefficient": 1.0,
        "train_rmse": float(np.sqrt(np.mean((y_share - x @ beta) ** 2))),
        "train_brier": brier(train_p, train_y),
        "holdout_brier": brier(hold_p, hold_y) if hold else None,
        "holdout_always_incumbent_brier": brier(always_inc, always_inc_y) if always_inc else None,
        "holdout_n_with_incumbent": len(always_inc),
        "holdout_source": cfg["holdout"]["source"],
        "holdout_source_url": cfg["holdout"]["source_url"],
        "notes": (
            "log_ratio_dem is 0 in the training extract (MEDSL has no receipts). "
            "The coefficient is unidentified in-sample. Fundraising at prediction "
            "time is reported in components_raw but does not move mu until a "
            "receipts-joined refit bumps model_version."
        ),
    }


def write_fit(summary: dict[str, Any], path: Path | None = None) -> Path:
    dest = path or FIT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def load_fit(path: Path | None = None) -> dict[str, Any]:
    dest = path or FIT_PATH
    if not dest.is_file():
        raise SeatModelError(f"fit summary missing: {dest}")
    return json.loads(dest.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def latest_generic_ballot(as_of: date | None = None) -> dict[str, Any] | None:
    rows = _read_csv(GENERIC_BALLOT_PATH)
    parsed: list[dict[str, str]] = []
    for row in rows:
        if not (row.get("date") or "").strip():
            continue
        day = date.fromisoformat(row["date"])
        if as_of is not None and day > as_of:
            continue
        parsed.append(row)
    if not parsed:
        return None
    parsed.sort(key=lambda r: r["date"])
    row = parsed[-1]
    dem = float(row["dem_share"])
    rep = float(row["rep_share"])
    if dem > 1.5:
        dem /= 100.0
        rep /= 100.0
    return {
        "date": row["date"],
        "dem_two_party": dem / (dem + rep) if dem + rep else 0.5,
        "source": row.get("source") or "",
        "source_url": row.get("source_url") or "",
    }


def poll_average(
    race_id: str,
    *,
    as_of: date,
    half_life_days: float,
    rows: Sequence[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    data = list(rows) if rows is not None else [
        r for r in _read_csv(DISTRICT_POLLS_PATH) if r.get("race_id") == race_id
    ]
    if not data:
        return None
    ln2 = math.log(2.0)
    num = 0.0
    den = 0.0
    used = 0
    for row in data:
        if row.get("race_id") and row["race_id"] != race_id:
            continue
        end_raw = row.get("end_date") or ""
        if not end_raw:
            continue
        end = date.fromisoformat(end_raw)
        if end > as_of:
            continue
        dem = float(row["dem_share"])
        rep = float(row["rep_share"])
        if dem > 1.5:
            dem /= 100.0
            rep /= 100.0
        if dem + rep <= 0:
            continue
        share = dem / (dem + rep)
        n = float(row.get("n") or 0.0)
        age = (as_of - end).days
        w = math.exp(-ln2 * age / half_life_days) * max(n, 1.0)
        num += w * share
        den += w
        used += 1
    if den <= 0:
        return None
    mu = num / den
    var = mu * (1 - mu) / max(den, 1.0)
    return {"mu": mu, "n_eff": den, "sigma": math.sqrt(max(var, 1e-8)), "n_polls": used}


def blend_mu(mu_f: float, sigma_f: float, poll: dict[str, Any] | None) -> tuple[float, float, str]:
    """Precision-weighted blend. No polls → fundamentals. n_eff → ∞ → poll mean."""
    if poll is None:
        return mu_f, sigma_f, "fundamentals_only"
    prec_f = 1.0 / (sigma_f**2)
    prec_p = 1.0 / (poll["sigma"] ** 2)
    mu = (mu_f * prec_f + poll["mu"] * prec_p) / (prec_f + prec_p)
    sigma = math.sqrt(1.0 / (prec_f + prec_p))
    return mu, sigma, "fundamentals_plus_polls"


def _fec_receipts_by_id() -> dict[str, float]:
    path = latest_snapshot()
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for row in payload.get("candidates") or []:
        cid = row.get("fec_candidate_id")
        rec = row.get("receipts")
        if cid and rec is not None:
            out[str(cid)] = float(rec)
    return out


def _two_party_lean(race) -> tuple[float | None, str]:
    lean = race.district_lean
    share = lean.pres_2024_two_party_dem_share
    label = "pres_2024"
    if share is None:
        share = lean.pres_2020_two_party_dem_share
        label = "pres_2020"
    if share is None:
        return None, "missing"
    value = float(share)
    if value > 1.5:
        value /= 100.0
    return value, label


def features_for_race(
    race,
    *,
    president_party: str,
    generic: dict[str, Any] | None,
    receipts: dict[str, float],
    national_pres_dem: float | None,
) -> tuple[np.ndarray, dict[str, float], dict[str, Any]]:
    dist_dem, lean_src = _two_party_lean(race)
    lean_status = lean_src
    if dist_dem is None or national_pres_dem is None:
        lean_rel = 0.0
        lean_status = "missing_zeroed"
    else:
        lean_rel = dist_dem - national_pres_dem
    inc_party = race.incumbent.party
    inc_dem = 1 if inc_party == "Democrat" else -1
    mid = _midterm_dem(race.election_date.year, president_party)
    dem_cand = race.challenger if race.challenger.party == "Democrat" else race.incumbent
    rep_cand = race.challenger if race.challenger.party == "Republican" else race.incumbent
    dem_rec = receipts.get(dem_cand.fec_candidate_id, 0.0)
    rep_rec = receipts.get(rep_cand.fec_candidate_id, 0.0)
    log_ratio = math.log((dem_rec + 1.0) / (rep_rec + 1.0))
    qual = 0
    if race.challenger.party == "Democrat" and race.challenger.prior_federal_service:
        qual = 1
    elif race.challenger.party == "Republican" and race.challenger.prior_federal_service:
        qual = -1
    nat_env = (generic["dem_two_party"] - 0.5) if generic else 0.0
    comps = {
        "lean_rel_dem": lean_rel,
        "inc_dem": float(inc_dem),
        "midterm_dem": float(mid),
        "log_ratio_dem": log_ratio,
        "qual_dem": float(qual),
        "nat_env": nat_env,
    }
    x = np.array(
        [1.0, lean_rel, float(inc_dem), float(mid), log_ratio, float(qual), nat_env],
        dtype=float,
    )
    meta = {
        "lean_status": lean_status,
        "environment_source": "generic_ballot" if generic else "neutral_default",
        "generic_date": None if not generic else generic["date"],
        "dem_receipts": dem_rec,
        "rep_receipts": rep_rec,
    }
    return x, comps, meta


def _plain_language(p_dem: float) -> str:
    if p_dem >= 0.95:
        return "Democrats are overwhelmingly likely to win"
    if p_dem >= 0.80:
        return "Democrats are likely to win, about 4 in 5"
    if p_dem >= 0.60:
        n = round(p_dem * 5)
        return f"Democrats are modest favorites, roughly {n} in 5"
    if p_dem >= 0.45:
        return "The race is a toss-up"
    if p_dem >= 0.20:
        n = round((1 - p_dem) * 5)
        return f"Republicans are modest favorites, roughly {n} in 5"
    if p_dem >= 0.05:
        return "Republicans are likely to win, about 4 in 5"
    return "Republicans are overwhelmingly likely to win"


def predict_races(
    *,
    as_of: date | None = None,
    registry: RaceRegistry | None = None,
    fit: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_seat_config()
    day = as_of or date.today()
    fit_doc = fit or load_fit()
    if fit_doc["model_version"] != cfg["model_version"]:
        raise SeatModelError(
            f"fit version {fit_doc['model_version']} != config {cfg['model_version']}"
        )
    beta = np.array([fit_doc["ols_beta"][n] for n in OLS_FEATURES], dtype=float)
    sigma_f = float(fit_doc["sigma"])
    generic = latest_generic_ballot(as_of=day)
    receipts = _fec_receipts_by_id()
    reg = registry or load_races()
    races_out = []
    for race in reg.races:
        if race.status.value != "tracked":
            continue
        _share, lean_src = _two_party_lean(race)
        nat = NATIONAL_PRES_DEM.get(lean_src)
        x, comps, meta = features_for_race(
            race,
            president_party=str(cfg["president_party"]),
            generic=generic,
            receipts=receipts,
            national_pres_dem=nat,
        )
        x_ols = x[:6]
        mu_f = float(x_ols @ beta) + comps["nat_env"]
        parts = {"intercept": float(beta[0])}
        for name, value, b in zip(OLS_FEATURES[1:], x_ols[1:], beta[1:], strict=True):
            parts[name] = float(b * value)
        parts["nat_env"] = comps["nat_env"]
        poll = poll_average(
            race.race_id,
            as_of=day,
            half_life_days=float(cfg["poll_half_life_days"]),
        )
        mu, sigma, blend_label = blend_mu(mu_f, sigma_f, poll)
        parts["polls"] = mu - mu_f
        p_dem = float(norm.cdf((mu - 0.5) / sigma))
        lo = mu - Z_80 * sigma
        hi = mu + Z_80 * sigma
        races_out.append(
            {
                "race_id": race.race_id,
                "district": race.district,
                "as_of": day.isoformat(),
                "model_version": cfg["model_version"],
                "prob_dem": round(p_dem, 4),
                "prob_rep": round(1.0 - p_dem, 4),
                "mu_dem_two_party": round(mu, 4),
                "mu_fundamentals": round(mu_f, 4),
                "share_lo": round(max(0.0, lo), 4),
                "share_hi": round(min(1.0, hi), 4),
                "sigma": round(sigma, 4),
                "blend": blend_label,
                "plain_language": _plain_language(p_dem),
                "decomposition": {k: round(v, 4) for k, v in parts.items()},
                "components_raw": {k: round(v, 4) for k, v in comps.items()},
                "meta": meta,
                "n_polls": 0 if poll is None else poll["n_polls"],
            }
        )
    return {
        "model_version": cfg["model_version"],
        "as_of": day.isoformat(),
        "sigma_fundamentals": sigma_f,
        "generic_ballot": generic,
        "races": races_out,
        "log": load_predictions(),
        "fit": {
            "n_train": fit_doc["n_train"],
            "holdout_brier": fit_doc.get("holdout_brier"),
            "holdout_always_incumbent_brier": fit_doc.get("holdout_always_incumbent_brier"),
            "holdout_source": fit_doc.get("holdout_source"),
        },
    }


def load_predictions(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or PREDICTIONS_PATH
    if not dest.is_file():
        return []
    with dest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def validate_predictions_append_only(
    current: Sequence[dict[str, str]],
    previous: Sequence[dict[str, str]],
) -> None:
    def key(row: dict[str, str]) -> tuple[str, str, str]:
        return (row["race_id"], row["date"], row["model_version"])

    cur_map = {key(r): r for r in current}
    if len(cur_map) != len(current):
        raise SeatModelError("predictions_seats.csv has duplicate (race_id, date, model_version)")
    for row in current:
        p = float(row["prob_dem"])
        if not 0.0 <= p <= 1.0:
            raise SeatModelError(f"prob_dem out of range: {row}")
    prev_map = {key(r): r for r in previous}
    missing = set(prev_map) - set(cur_map)
    if missing:
        raise SeatModelError(f"append-only violation, missing keys: {sorted(missing)[:8]}")
    for k, old in prev_map.items():
        new = cur_map[k]
        if (old.get("prob_dem"), old.get("model_version")) != (
            new.get("prob_dem"),
            new.get("model_version"),
        ):
            raise SeatModelError(f"append-only violation, mutated row {k}")


def validate_predictions_file(path: Path | None = None) -> list[dict[str, str]]:
    dest = path or PREDICTIONS_PATH
    rows = load_predictions(dest)
    validate_predictions_append_only(rows, rows)
    return rows


def append_predictions(payload: dict[str, Any], *, path: Path | None = None) -> Path:
    dest = path or PREDICTIONS_PATH
    existing = load_predictions(dest)
    by_key = {(r["race_id"], r["date"], r["model_version"]): r for r in existing}
    as_of = payload["as_of"]
    version = payload["model_version"]
    for race in payload["races"]:
        k = (race["race_id"], as_of, version)
        if k in by_key:
            continue
        by_key[k] = {
            "race_id": race["race_id"],
            "date": as_of,
            "prob_dem": f"{race['prob_dem']:.4f}",
            "model_version": version,
        }
    rows = [by_key[k] for k in sorted(by_key)]
    validate_predictions_append_only(rows, existing)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(PREDICTION_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return dest
