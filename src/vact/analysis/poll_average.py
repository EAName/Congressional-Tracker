"""Generic-ballot poll average from a primary-poll archive.

Aggregator output is never ingested (SEAT_MODEL_SPEC.md). The archive is
`data/generic_ballot_polls.csv`; every published number here is recomputed from
it at export time, like every other metric in this repo (AGENTS.md §8).

Method, in order:

1. Each poll is dated at the midpoint of its field period and converted to a
   two-party Democratic share.
2. Sample type (LV / RV / adults) is shifted onto a likely-voter basis using
   configured offsets. Those are priors, not estimates, until the archive holds
   enough same-release LV/RV pairs to identify them.
3. House effects are the per-pollster mean residual against the average,
   shrunk toward zero by `n / (n + shrink_k)` and re-estimated for a few
   iterations. A firm with one poll keeps a fraction of its apparent lean.
4. The trend at each date is a weighted mean over all polls, weighting by
   sample size, an exponential recency kernel centred on that date, and a
   per-pollster frequency penalty so one prolific firm cannot carry the line.
5. The band is predictive, not a confidence interval on the mean: it answers
   "where would the next poll land", which is what the shaded region on a
   published average conventionally shows. It combines the weighted spread of
   polls around the trend with the sampling error of a single poll. The sampling
   floor matters: with a thin archive one poll can dominate the local kernel, the
   observed spread collapses toward zero, and a band built on spread alone would
   claim near-certainty from a single survey.
"""

from __future__ import annotations

import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from vact.paths import REPO_ROOT

POLLS_PATH = REPO_ROOT / "data" / "generic_ballot_polls.csv"
CONFIG_PATH = REPO_ROOT / "config" / "polls.yaml"

# Two-sided normal quantiles for the predictive band.
_Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600}


class PollArchiveError(ValueError):
    """Archive row failed validation."""


@dataclass(frozen=True)
class Poll:
    pollster: str
    sponsor: str
    start_date: date
    end_date: date
    n: int
    population: str
    dem: float
    rep: float
    partisan: str
    source_url: str

    @property
    def mid_date(self) -> date:
        return self.start_date + (self.end_date - self.start_date) / 2

    @property
    def dem_two_party(self) -> float:
        total = self.dem + self.rep
        if total <= 0:
            raise PollArchiveError(f"{self.pollster}: dem+rep is zero")
        return self.dem / total


def load_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8"))


def _pct(value: str, field: str, pollster: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as err:
        raise PollArchiveError(f"{pollster}: {field} is not numeric: {value!r}") from err
    if num <= 0:
        raise PollArchiveError(f"{pollster}: {field} must be positive")
    return num / 100.0 if num > 1.5 else num


def load_polls(path: Path | None = None) -> list[Poll]:
    dest = path or POLLS_PATH
    if not dest.is_file():
        return []
    polls: list[Poll] = []
    with dest.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            pollster = (row.get("pollster") or "").strip()
            if not pollster:
                continue
            start = date.fromisoformat((row["start_date"] or "").strip())
            end = date.fromisoformat((row["end_date"] or "").strip())
            if end < start:
                raise PollArchiveError(f"{pollster}: end_date {end} before start_date {start}")
            population = (row.get("population") or "lv").strip().lower()
            if population not in {"lv", "rv", "a"}:
                raise PollArchiveError(f"{pollster}: population must be lv/rv/a, got {population!r}")
            try:
                n = int(float(row.get("n") or 0))
            except ValueError as err:
                raise PollArchiveError(f"{pollster}: n is not numeric") from err
            if n <= 0:
                raise PollArchiveError(f"{pollster}: n must be positive")
            polls.append(
                Poll(
                    pollster=pollster,
                    sponsor=(row.get("sponsor") or "").strip(),
                    start_date=start,
                    end_date=end,
                    n=n,
                    population=population,
                    dem=_pct(row.get("dem", ""), "dem", pollster),
                    rep=_pct(row.get("rep", ""), "rep", pollster),
                    partisan=(row.get("partisan") or "").strip().lower(),
                    source_url=(row.get("source_url") or "").strip(),
                )
            )
    polls.sort(key=lambda p: (p.mid_date, p.pollster))
    return polls


def _adjusted_share(poll: Poll, cfg: dict[str, Any]) -> float:
    offsets = cfg["sample_type"]["offsets"]
    return poll.dem_two_party + float(offsets.get(poll.population, 0.0))


def _sampling_var(poll: Poll) -> float:
    """Variance of a single poll's two-party share from sampling alone."""
    two_party_n = max(1.0, poll.n * (poll.dem + poll.rep))
    p = poll.dem_two_party
    return p * (1.0 - p) / two_party_n


def _recency_weight(poll_day: date, at: date, half_life: float) -> float:
    age = abs((at - poll_day).days)
    return math.exp(-math.log(2.0) * age / half_life)


def _base_weights(polls: list[Poll]) -> list[float]:
    """Sample size, damped, divided by how prolific the firm is."""
    counts: dict[str, int] = {}
    for p in polls:
        counts[p.pollster] = counts.get(p.pollster, 0) + 1
    out = []
    for p in polls:
        freq_penalty = math.sqrt(counts[p.pollster])
        out.append(math.sqrt(p.n) / freq_penalty)
    return out


def estimate_house_effects(
    polls: list[Poll], cfg: dict[str, Any] | None = None
) -> dict[str, float]:
    """Per-pollster mean residual against the running average, shrunk to zero."""
    conf = cfg or load_config()
    if not polls:
        return {}
    half_life = float(conf["half_life_days"])
    shrink_k = float(conf["house_effect"]["shrink_k"])
    max_abs = float(conf["house_effect"]["max_abs"])
    shares = [_adjusted_share(p, conf) for p in polls]
    base = _base_weights(polls)
    effects: dict[str, float] = {}

    for _ in range(int(conf["house_effect"]["iterations"])):
        residuals: dict[str, list[float]] = {}
        for i, poll in enumerate(polls):
            num = den = 0.0
            for j, other in enumerate(polls):
                if j == i:
                    continue
                w = base[j] * _recency_weight(other.mid_date, poll.mid_date, half_life)
                num += w * (shares[j] - effects.get(other.pollster, 0.0))
                den += w
            if den <= 0:
                continue
            consensus = num / den
            corrected = shares[i]
            residuals.setdefault(poll.pollster, []).append(corrected - consensus)
        effects = {}
        for pollster, res in residuals.items():
            raw = sum(res) / len(res)
            shrunk = raw * (len(res) / (len(res) + shrink_k))
            effects[pollster] = max(-max_abs, min(max_abs, shrunk))
    return effects


def trend_series(
    polls: list[Poll],
    *,
    cfg: dict[str, Any] | None = None,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Daily weighted trend with a predictive band."""
    conf = cfg or load_config()
    if len(polls) < int(conf["min_polls"]):
        return []
    half_life = float(conf["half_life_days"])
    effects = estimate_house_effects(polls, conf)
    shares = [_adjusted_share(p, conf) - effects.get(p.pollster, 0.0) for p in polls]
    base = _base_weights(polls)
    z = _Z.get(round(float(conf["band_coverage"]), 2), 1.6449)

    end = as_of or polls[-1].mid_date
    start = max(polls[0].mid_date, end - timedelta(days=int(conf["window_days"])))
    out: list[dict[str, Any]] = []
    day = start
    while day <= end:
        num = den = 0.0
        weights: list[float] = []
        for i, poll in enumerate(polls):
            w = base[i] * _recency_weight(poll.mid_date, day, half_life)
            weights.append(w)
            num += w * shares[i]
            den += w
        if den > 0:
            mu = num / den
            eff_n = (den**2) / sum(w * w for w in weights) if weights else 0.0
            # Between-poll dispersion, bias-corrected by the effective count.
            var_between = sum(w * (s - mu) ** 2 for w, s in zip(weights, shares)) / den
            if eff_n > 1.0:
                var_between *= eff_n / (eff_n - 1.0)
            else:
                var_between = 0.0
            # Sampling error a fresh poll would carry on its own, weighted the
            # same way. Two-party responders only.
            var_sample = (
                sum(w * _sampling_var(p) for w, p in zip(weights, polls)) / den
            )
            sd = math.sqrt(max(var_between, 0.0) + var_sample)
            out.append(
                {
                    "date": day.isoformat(),
                    "dem_two_party": round(mu, 5),
                    "lo": round(max(0.0, mu - z * sd), 5),
                    "hi": round(min(1.0, mu + z * sd), 5),
                    "effective_n_polls": round(eff_n, 2),
                    "sd": round(sd, 5),
                }
            )
        day += timedelta(days=1)
    return out


def _headline_shares(polls: list[Poll], series_point: dict[str, Any]) -> tuple[float, float]:
    """Split the two-party trend back into headline D/R using recent third-party share."""
    recent = polls[-10:] if len(polls) > 10 else polls
    other = sum(max(0.0, 1.0 - (p.dem + p.rep)) for p in recent) / len(recent)
    two_party = 1.0 - other
    dem = series_point["dem_two_party"] * two_party
    return dem, two_party - dem


def build_generic_ballot(
    *,
    polls_path: Path | None = None,
    cfg: dict[str, Any] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    conf = cfg or load_config()
    polls = load_polls(polls_path)
    series = trend_series(polls, cfg=conf, as_of=as_of)
    effects = estimate_house_effects(polls, conf) if polls else {}
    payload: dict[str, Any] = {
        "version": int(conf["version"]),
        "as_of": (as_of or (polls[-1].mid_date if polls else date.today())).isoformat(),
        "n_polls": len(polls),
        "min_polls": int(conf["min_polls"]),
        "band_coverage": float(conf["band_coverage"]),
        "half_life_days": float(conf["half_life_days"]),
        "sample_type_offsets_are_priors": bool(conf["sample_type"]["offsets_are_priors"]),
        "series": series,
        "environment_gate": {},
        "house_effects": {k: round(v, 5) for k, v in sorted(effects.items())},
        "polls": [
            {
                "pollster": p.pollster,
                "sponsor": p.sponsor,
                "date": p.mid_date.isoformat(),
                "start_date": p.start_date.isoformat(),
                "end_date": p.end_date.isoformat(),
                "n": p.n,
                "population": p.population,
                "dem": round(p.dem, 5),
                "rep": round(p.rep, 5),
                "dem_two_party": round(p.dem_two_party, 5),
                "partisan": p.partisan,
                "source_url": p.source_url,
            }
            for p in polls
        ],
    }
    if series:
        last = series[-1]
        dem, rep = _headline_shares(polls, last)
        payload["current"] = {
            "date": last["date"],
            "dem": round(dem, 5),
            "rep": round(rep, 5),
            "dem_two_party": last["dem_two_party"],
            "margin_pp": round((dem - rep) * 100.0, 2),
            "lo": last["lo"],
            "hi": last["hi"],
        }
    else:
        payload["current"] = None
        payload["status"] = (
            f"archive holds {len(polls)} poll(s); {conf['min_polls']} required before "
            "an average is published"
        )
    payload["environment_gate"] = environment_support(payload, conf, polls=polls)
    return payload


def _point_estimate(polls: list[Poll], day: date, cfg: dict[str, Any]) -> float | None:
    """Weighted trend at a single date. Cheap enough to jackknife."""
    if len(polls) < int(cfg["min_polls"]):
        return None
    half_life = float(cfg["half_life_days"])
    effects = estimate_house_effects(polls, cfg)
    shares = [_adjusted_share(p, cfg) - effects.get(p.pollster, 0.0) for p in polls]
    base = _base_weights(polls)
    num = den = 0.0
    for i, poll in enumerate(polls):
        w = base[i] * _recency_weight(poll.mid_date, day, half_life)
        num += w * shares[i]
        den += w
    return num / den if den > 0 else None


def single_poll_influence_pp(
    polls: list[Poll], cfg: dict[str, Any] | None = None, *, as_of: date | None = None
) -> float | None:
    """Largest move in the current average, in margin points, from dropping any
    one poll.

    This is the question that actually matters for using the average as a
    forecast input: can one survey swing it? A raw poll count cannot answer that
    — twenty polls from one firm in one week are less stable than eight from
    eight firms — so the gate measures the thing directly.
    """
    conf = cfg or load_config()
    if len(polls) <= int(conf["min_polls"]):
        return None
    day = as_of or polls[-1].mid_date
    full = _point_estimate(polls, day, conf)
    if full is None:
        return None
    worst = 0.0
    for i in range(len(polls)):
        keep = [p for j, p in enumerate(polls) if j != i]
        got = _point_estimate(keep, day, conf)
        if got is None:
            continue
        worst = max(worst, abs(got - full))
    # two-party share -> margin points
    return worst * 200.0


def aggregate_sampling_se_pp(
    polls: list[Poll], cfg: dict[str, Any] | None = None, *, as_of: date | None = None
) -> float | None:
    """Sampling standard error of the current average, in margin points.

    This is the irreducible part: the noise that remains even with a perfectly
    balanced archive. It anchors the stability gate, because compositional
    leverage is only worth policing while it is small next to the error nobody
    can design away.
    """
    conf = cfg or load_config()
    if not polls:
        return None
    day = as_of or polls[-1].mid_date
    half_life = float(conf["half_life_days"])
    base = _base_weights(polls)
    w = [base[i] * _recency_weight(p.mid_date, day, half_life) for i, p in enumerate(polls)]
    den = sum(w)
    if den <= 0:
        return None
    var = sum((wi / den) ** 2 * _sampling_var(p) for wi, p in zip(w, polls))
    return math.sqrt(var) * 200.0


def influence_limit_pp(
    polls: list[Poll], cfg: dict[str, Any] | None = None, *, as_of: date | None = None
) -> float:
    """Gate threshold, derived rather than picked.

    A fixed constant is arbitrary and does not age: as the archive deepens the
    sampling error falls, and a bar that stays put quietly gets looser in
    relative terms. Tying it to a fraction of the aggregate's own sampling SE
    keeps the standard fixed in the units that matter, with a floor so a very
    deep archive cannot drive it to zero.
    """
    conf = cfg or load_config()
    gate = conf.get("environment_gate") or {}
    ratio = float(gate.get("influence_vs_sampling_se", 0.5))
    floor = float(gate.get("influence_floor_pp", 0.5))
    se = aggregate_sampling_se_pp(polls, conf, as_of=as_of)
    if se is None:
        return floor
    return max(floor, ratio * se)


def firm_influence_pp(
    polls: list[Poll], cfg: dict[str, Any] | None = None, *, as_of: date | None = None
) -> tuple[float | None, str | None]:
    """Largest move in the current average, in margin points, from dropping every
    poll by any one firm.

    Strictly the stronger test. A firm that polls often has each of its surveys
    downweighted by the frequency penalty, so no single one of them looks
    influential even when the firm collectively carries the estimate. Dropping
    the firm is the question a reader would actually ask.
    """
    conf = cfg or load_config()
    if not polls:
        return None, None
    day = as_of or polls[-1].mid_date
    full = _point_estimate(polls, day, conf)
    if full is None:
        return None, None
    worst, who = 0.0, None
    for firm in {p.pollster for p in polls}:
        keep = [p for p in polls if p.pollster != firm]
        if len(keep) < int(conf["min_polls"]):
            continue
        got = _point_estimate(keep, day, conf)
        if got is not None and abs(got - full) > worst:
            worst, who = abs(got - full), firm
    if who is None:
        return None, None
    return worst * 200.0, who


def environment_support(
    doc: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    *,
    polls: list[Poll] | None = None,
) -> dict[str, Any]:
    """Whether the archive can carry `nat_env`, and why not if it cannot.

    Displaying an average and letting it move every race forecast are different
    bars. The archive at six polls had a single-poll influence of 1.4 margin
    points and moved a Trump+12 district's win probability by 23; at ten it is
    0.8 and the estimate sits within a point of published averages.
    """
    conf = cfg or load_config()
    gate = conf.get("environment_gate") or {}
    min_polls = int(gate.get("min_polls", 0))
    rows = polls if polls is not None else load_polls()
    max_influence = influence_limit_pp(rows, conf)
    max_firm = max_influence * float(gate.get("firm_limit_multiple", 1.5))
    sampling_se = aggregate_sampling_se_pp(rows, conf)
    influence = single_poll_influence_pp(rows, conf)
    firm_inf, firm_name = firm_influence_pp(rows, conf)
    reasons = []
    if doc["n_polls"] < min_polls:
        reasons.append(f"{doc['n_polls']} polls, {min_polls} needed")
    if influence is None:
        reasons.append("not enough polls to measure stability")
    elif influence > max_influence:
        reasons.append(
            f"one poll can move the average {influence:.1f} points, limit {max_influence:.1f}"
        )
    if firm_inf is not None and firm_inf > max_firm:
        reasons.append(
            f"dropping {firm_name} moves the average {firm_inf:.1f} points, "
            f"limit {max_firm:.1f}"
        )
    series = doc.get("series") or []
    eff = float(series[-1]["effective_n_polls"]) if series else 0.0
    return {
        "ok": not reasons,
        "n_polls": doc["n_polls"],
        "n_firms": len({p.pollster for p in rows}),
        "effective_n_polls": round(eff, 2),
        "single_poll_influence_pp": None if influence is None else round(influence, 2),
        "max_single_poll_influence_pp": round(max_influence, 2),
        "aggregate_sampling_se_pp": None if sampling_se is None else round(sampling_se, 2),
        "firm_influence_pp": None if firm_inf is None else round(firm_inf, 2),
        "most_influential_firm": firm_name,
        "max_firm_influence_pp": round(max_firm, 2),
        "min_polls": min_polls,
        "reasons": reasons,
    }


def latest_two_party(
    *, polls_path: Path | None = None, as_of: date | None = None
) -> dict[str, Any] | None:
    """Newest trend point, in the shape seat_model expects for nat_env.

    Returns None while the archive is too thin to drive a forecast, which leaves
    the seat models on their neutral default rather than on a number two
    pollsters are carrying.
    """
    doc = build_generic_ballot(polls_path=polls_path, as_of=as_of)
    current = doc.get("current")
    if not current:
        return None
    if not environment_support(doc, polls=load_polls(polls_path))["ok"]:
        return None
    return {
        "date": current["date"],
        "dem_two_party": current["dem_two_party"],
        "source": f"vact poll average ({doc['n_polls']} primary polls)",
        "source_url": "",
    }
