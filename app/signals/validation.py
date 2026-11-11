"""P3: calibrate the decision framework's regime thresholds on real data.

Why this exists
---------------
The BUY/SELL/ABSTAIN rule is conditioned on a market regime (trend x volatility).
If those labels are mostly noise, the rule's thresholds cannot mean anything: a
threshold tuned on unstable labels is a threshold tuned on randomness.

What is measured
----------------
Every bar gets two labellings of the *same* bar, so an Adjusted Rand Index (ARI)
between them is a well-posed partition comparison:

* **current regime** - trend x volatility of bars ``0..t`` (what the rule sees);
* **forward regime** - trend x volatility of bars ``t+1..t+H`` (what happened next;
  used only for validation, never by a decision).

1. **Observed persistence.**  ``observed_ari = ARI(current, forward)``.  A market
   whose state carries information has labels that persist; a random walk does not.
2. **Null distribution.**  The log-returns are randomly permuted (structure
   destroyed, marginal distribution kept) ``n_permutations`` times and both
   labellings are recomputed on the permuted path.  ``validation_null_ari_max`` is
   the ``1 - validation_alpha`` quantile of that null; when ``None`` it is
   calibrated from the data.
3. **Stability.**  The aligned (current, forward) label pairs are resampled with a
   moving-block bootstrap ``n_bootstrap`` times; the ARI is recomputed on every
   resample.  The median and the 5% lower bound must both clear
   ``validation_stability_threshold`` (when ``None``: calibrated to the null bound).

What is NOT claimed
-------------------
Passing this test does not validate ``min_edge``, ``max_downside`` or sizing as
profitable.  It only says the regime labels are reproducible and distinguishable
from chance, which is a precondition for tuning those thresholds at all.
``SignalParams`` values are echoed in the report so the run is self-describing.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.core import config, timeframes
from app.core.errors import DataValidationError, require
from app.signals.regime import RegimeParams, regime_labels

MIN_SERIES_BARS = 60


@dataclass(frozen=True)
class ValidationParams:
    """Calibration knobs (names match the documented ``validation_*`` settings)."""

    alpha: float = config.VALIDATION_ALPHA  # validation_alpha: significance of the null bound
    null_ari_max: float | None = config.VALIDATION_NULL_ARI_MAX  # None -> calibrated from permutations
    stability_threshold: float | None = config.VALIDATION_STABILITY_THRESHOLD  # None -> calibrated
    n_permutations: int = config.N_PERMUTATIONS
    n_bootstrap: int = config.N_BOOTSTRAP
    seed: int = 20260101
    block_size: int | None = None  # moving-block bootstrap block length; None -> automatic
    forward_window: int = 10  # H: bars used for the forward regime labelling
    interval: str | None = None  # None -> config.INTERVAL
    regime: RegimeParams = field(default_factory=RegimeParams)

    def __post_init__(self) -> None:
        require(math.isfinite(self.alpha) and 0 < self.alpha < 1, "alpha must be strictly between 0 and 1")
        require(self.n_permutations >= 2, "n_permutations must be at least 2")
        require(self.n_bootstrap >= 2, "n_bootstrap must be at least 2")
        if self.null_ari_max is not None:
            require(math.isfinite(self.null_ari_max) and -1 <= self.null_ari_max <= 1,
                    "null_ari_max must be between -1 and 1")
        if self.stability_threshold is not None:
            require(math.isfinite(self.stability_threshold) and -1 <= self.stability_threshold <= 1,
                    "stability_threshold must be between -1 and 1")
        if self.block_size is not None:
            require(self.block_size >= 2, "block_size must be at least 2")
        require(2 <= self.forward_window <= config.MAX_HORIZON,
                f"forward_window must be between 2 and {config.MAX_HORIZON}")
        if self.interval is not None:
            timeframes.normalize(self.interval)  # controlled error on a bad interval

    def as_plain(self) -> dict[str, Any]:
        """Documented names (``validation_*``) plus the internal fields, for the report."""
        return {
            "validation_alpha": self.alpha,
            "validation_null_ari_max": self.null_ari_max,
            "validation_stability_threshold": self.stability_threshold,
            "n_permutations": self.n_permutations,
            "n_bootstrap": self.n_bootstrap,
            "forward_window": self.forward_window,
            "block_size": self.block_size,
            "seed": self.seed,
            "interval": self.interval,
            "alpha": self.alpha,
            "null_ari_max": self.null_ari_max,
            "stability_threshold": self.stability_threshold,
            "regime": asdict(self.regime),
        }


def adjusted_rand_index(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    """Adjusted Rand Index of two label sequences (Hubert & Arabie, 1985).

    ``1.0`` = identical partitions, ``~0`` = chance agreement, negative = worse
    than chance.  Positions where either label is missing are ignored first by
    ``compare_labels``; here both inputs must be complete and the same length.
    """
    x = np.asarray(a, dtype=object)
    y = np.asarray(b, dtype=object)
    if len(x) != len(y):
        raise DataValidationError(f"ARI needs equal lengths, got {len(x)} and {len(y)}")
    n = len(x)
    if n < 2:
        return 1.0
    table = pd.crosstab(pd.Series(x), pd.Series(y)).to_numpy()
    if table.size == 0:
        return 1.0

    def comb2(values: np.ndarray) -> float:
        v = np.asarray(values, dtype=np.float64)
        return float(np.sum(v * (v - 1.0) / 2.0))

    sum_cells = comb2(table.ravel())
    sum_rows = comb2(table.sum(axis=1))
    sum_cols = comb2(table.sum(axis=0))
    total = n * (n - 1) / 2.0
    expected = sum_rows * sum_cols / total
    max_index = 0.5 * (sum_rows + sum_cols)
    denominator = max_index - expected
    if abs(denominator) < 1e-12:  # both labellings are trivial (one cluster)
        return 1.0 if np.array_equal(x, y) else 0.0
    return float((sum_cells - expected) / denominator)


def compare_labels(reference: pd.Series, other: pd.Series) -> float | None:
    """ARI over the positions where both label sequences are defined."""
    ref = pd.Series(reference).reset_index(drop=True)
    oth = pd.Series(other).reset_index(drop=True)
    if len(ref) != len(oth):
        raise DataValidationError("label sequences must have the same length")
    mask = ref.notna() & oth.notna()
    if int(mask.sum()) < 2:
        return None
    return adjusted_rand_index(ref[mask], oth[mask])


def forward_regime_labels(
    close: pd.Series, params: RegimeParams, bars_per_year: float, forward_window: int
) -> pd.Series:
    """Regime of the NEXT ``forward_window`` bars, one label per bar (the ``t+1..t+H`` window).

    This deliberately uses future data: it is a validation target, never an input to
    ``decide`` or ``decide_at``.
    """
    c = pd.Series(np.asarray(close, dtype=np.float64)).reset_index(drop=True)
    forward_return = c.shift(-forward_window) / c - 1.0
    forward_vol = (
        np.log(c).diff().rolling(forward_window).std().shift(-forward_window) * np.sqrt(bars_per_year)
    )
    pct = forward_vol.rolling(params.vol_history, min_periods=1).rank(pct=True, method="average")
    trend = pd.Series(np.select([forward_return > 0, forward_return < 0], ["up", "down"], default="sideways"),
                      index=c.index, dtype=object)
    level = pd.Series(np.select([pct <= params.low_pct, pct >= params.high_pct], ["low", "high"], default="normal"),
                      index=c.index, dtype=object)
    valid = forward_return.notna() & pct.notna()
    labels = trend.astype(str) + "|" + level.astype(str)
    return labels.where(valid)


def _path_from_returns(returns: np.ndarray, start: float = 100.0) -> np.ndarray:
    returns = np.asarray(returns, dtype=np.float64)
    return start * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))


def default_block_size(n_returns: int) -> int:
    """Rule of thumb: ~n^(1/3) bars, clamped to [5, 60] so blocks stay meaningful."""
    return int(min(60, max(5, round(n_returns ** (1 / 3) * 2))))


def _block_positions(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Indices of a moving-block bootstrap resample of ``n`` aligned observations."""
    block = max(2, min(block, n))
    out: list[np.ndarray] = []
    while sum(len(p) for p in out) < n:
        start = int(rng.integers(0, n - block + 1))
        out.append(np.arange(start, start + block))
    return np.concatenate(out)[:n]


def _persistence_ari(close: pd.Series, params: ValidationParams, bars_per_year: float) -> float | None:
    """ARI between the current and the forward regime labelling of the same bars."""
    current = regime_labels(close, params.regime, bars_per_year)
    forward = forward_regime_labels(close, params.regime, bars_per_year, params.forward_window)
    return compare_labels(current, forward)


def calibrate_thresholds(close: pd.Series | np.ndarray, params: ValidationParams = ValidationParams()) -> dict[str, Any]:
    """Run the permutation null and the bootstrap stability test on one close series.

    ``close`` must be in chronological order and end at the newest bar.  The result
    is a plain-JSON-serialisable report; nothing here changes a stored dataset.
    """
    interval = timeframes.normalize(params.interval or config.INTERVAL)
    bpy_factor = float(timeframes.bars_per_year(interval))
    c = pd.Series(np.asarray(close, dtype=np.float64)).reset_index(drop=True)
    min_bars = max(params.regime.min_bars, MIN_SERIES_BARS, 2 * params.forward_window)
    if len(c) < min_bars:
        raise DataValidationError(f"threshold calibration needs at least {min_bars} bars, got {len(c)}")
    if not (np.isfinite(c).all() and (c > 0).all()):
        raise DataValidationError("threshold calibration needs finite, positive closes")

    current = regime_labels(c, params.regime, bpy_factor)
    forward = forward_regime_labels(c, params.regime, bpy_factor, params.forward_window)
    observed = compare_labels(current, forward)
    if observed is None:
        raise DataValidationError("not enough jointly labelled bars: increase the series length")

    returns = np.diff(np.log(c.to_numpy()))
    rng = np.random.default_rng(params.seed)

    null_aris: list[float] = []
    for _ in range(params.n_permutations):
        permuted = pd.Series(_path_from_returns(rng.permutation(returns)))
        ari = _persistence_ari(permuted, params, bpy_factor)
        if ari is not None:
            null_aris.append(ari)
    if not null_aris:  # pragma: no cover - guarded above
        raise DataValidationError("could not compare any permutation labelling")

    block = params.block_size or default_block_size(int((current.notna() & forward.notna()).sum()))
    mask = (current.notna() & forward.notna()).to_numpy()
    positions = np.flatnonzero(mask)
    cur = current.to_numpy()[positions]
    fwd = forward.to_numpy()[positions]
    boot_aris: list[float] = []
    for _ in range(params.n_bootstrap):
        pick = _block_positions(len(positions), block, rng)
        boot_aris.append(adjusted_rand_index(cur[pick], fwd[pick]))

    null_arr = np.asarray(null_aris, dtype=np.float64)
    boot_arr = np.asarray(boot_aris, dtype=np.float64)
    observed_null_quantile = float(np.quantile(null_arr, 1.0 - params.alpha))
    null_auto = params.null_ari_max is None
    null_bound = observed_null_quantile if null_auto else float(params.null_ari_max)  # type: ignore[arg-type]
    stability_auto = params.stability_threshold is None
    threshold = float(null_bound) if stability_auto else float(params.stability_threshold)  # type: ignore[arg-type]
    stability_median = float(np.median(boot_arr))
    stability_p05 = float(np.quantile(boot_arr, 0.05))

    threshold_consistent = threshold >= null_bound
    stable = bool(stability_median >= threshold and stability_p05 >= threshold)
    beats_null = bool(observed >= threshold)
    passed = bool(stable and beats_null and threshold_consistent)
    warnings: list[str] = []
    if not threshold_consistent:
        warnings.append(
            f"stability_threshold={threshold:.4f} is below the null bound {null_bound:.4f}: pure noise would pass"
        )
    if params.null_ari_max is not None and not null_auto and params.null_ari_max < observed_null_quantile:
        warnings.append(
            f"validation_null_ari_max={params.null_ari_max:.4f} is below the observed "
            f"{100 * (1 - params.alpha):.0f}% null quantile {observed_null_quantile:.4f}"
        )
    if not beats_null:
        warnings.append(
            "observed regime persistence does not clear the null bound: the labels are indistinguishable from "
            "chance on this history; the P3 thresholds are not validated"
        )
    elif not stable:
        warnings.append(
            "regime persistence is significant but not stable under the block bootstrap; do not tune decision "
            "thresholds on it yet (longer history or a longer forward window may help)"
        )

    return {
        "kind": "threshold_validation",
        "interval": interval,
        "bars_per_year": bpy_factor,
        "n_bars": int(len(c)),
        "n_labelled_bars": int(mask.sum()),
        "forward_window": params.forward_window,
        "label_counts": {str(k): int(v) for k, v in current.dropna().value_counts().sort_index().items()},
        "params": params.as_plain(),
        "thresholds": {
            "alpha": params.alpha,
            "null_ari_max": null_bound,
            "null_ari_max_auto": null_auto,
            "stability_threshold": threshold,
            "stability_threshold_auto": stability_auto,
            "consistent": threshold_consistent,
        },
        "observed_ari": observed,
        "null": {
            "n": len(null_arr),
            "ari_mean": float(null_arr.mean()),
            "ari_p95": float(np.quantile(null_arr, 0.95)),
            "ari_max": float(null_arr.max()),
            "ari_by_alpha": observed_null_quantile,
        },
        "bootstrap": {
            "n": len(boot_arr),
            "block_size": int(block),
            "ari_median": stability_median,
            "ari_p05": stability_p05,
            "ari_min": float(boot_arr.min()),
            "ari_max": float(boot_arr.max()),
        },
        "stability_ari": stability_median,
        "passed": passed,
        "warnings": warnings,
        "interpretation": (
            "ARI compares the regime of each bar (trend x volatility from past data) with the regime of the "
            "next forward_window bars. The null bound is the ARI reached after permuting returns, so it is "
            "what chance alone produces; stability is the block-bootstrap agreement. A pass means the labels "
            "carry information beyond chance and reproduce, NOT that the rules are profitable."
        ),
        "note": "Research output only; not financial advice.",
    }
