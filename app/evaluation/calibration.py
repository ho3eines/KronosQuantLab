"""P2: out-of-sample interval calibration (split conformal scaling of P10-P90).

The raw P10-P90 band of a sampler has no coverage guarantee.  We measure a
per-origin nonconformity score on EARLIER origins and widen/narrow the band by
one factor, then check coverage on LATER origins the factor never saw.

score = how many "half-widths" the realised value sits from the median:
    y >= p50:  (y - p50) / (p90 - p50)      y < p50:  (p50 - y) / (p50 - p10)
A score <= 1 means the value was inside the raw band.  The factor is the split
conformal quantile of the calibration scores: the k-th smallest with
k = ceil((n + 1) * level).  If k > n there are too few origins and the factor is
reported as unavailable instead of being guessed.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.core.config import CLOSE_INDEX
from app.core.errors import require
from app.evaluation import metrics

MIN_WIDTH = 1e-12


def interval_scores(p10: np.ndarray, p50: np.ndarray, p90: np.ndarray, y: np.ndarray) -> np.ndarray:
    up = np.maximum(p90 - p50, MIN_WIDTH)
    down = np.maximum(p50 - p10, MIN_WIDTH)
    return np.where(y >= p50, (y - p50) / up, (p50 - y) / down)


def conformal_factor(scores: np.ndarray, level: float = 0.8) -> float | None:
    n = len(scores)
    k = math.ceil((n + 1) * level)
    if n == 0 or k > n:
        return None
    return float(np.sort(scores)[k - 1])


def apply_factor(p10: np.ndarray, p50: np.ndarray, p90: np.ndarray, factor: float) -> tuple[np.ndarray, np.ndarray]:
    return p50 - factor * (p50 - p10), p50 + factor * (p90 - p50)


def min_origins_for(level: float) -> int:
    return math.ceil(level / (1 - level))


def calibrate_split(
    paths: np.ndarray, actual: np.ndarray, horizons: tuple[int, ...], calib_fraction: float = 0.5, level: float = 0.8
) -> list[dict[str, Any]]:
    """``paths`` (origins, n_paths, H, 6) and ``actual`` (origins, H, 6) in chronological order.

    Uses the forecast at step h (endpoint) for each horizon h.
    """
    require(0 < level < 1, f"level must be strictly between 0 and 1, got {level}")
    require(0 < calib_fraction < 1, f"calib_fraction must be strictly between 0 and 1, got {calib_fraction}")
    n = paths.shape[0]
    n_cal = int(round(n * calib_fraction))
    out: list[dict[str, Any]] = []
    if n == 0 or paths.shape[1] < 2:
        return out
    close = paths[..., CLOSE_INDEX]
    p10, p50, p90 = metrics.path_quantiles(np.moveaxis(close, 1, 0))  # each (origins, H)
    y_all = actual[..., CLOSE_INDEX]
    for h in horizons:
        i = h - 1
        s = interval_scores(p10[:, i], p50[:, i], p90[:, i], y_all[:, i])
        factor = conformal_factor(s[:n_cal], level)
        row: dict[str, Any] = {
            "horizon": h, "level": level, "n_calibration": n_cal, "n_test": n - n_cal, "factor": factor,
            "min_calibration_origins_needed": min_origins_for(level),
            "raw_coverage_all": float(np.mean(s <= 1.0)),
            "raw_coverage_test": float(np.mean(s[n_cal:] <= 1.0)) if n > n_cal else None,
            "calibrated_coverage_test": None,
        }
        if factor is not None and n > n_cal:
            lo, hi = apply_factor(p10[n_cal:, i], p50[n_cal:, i], p90[n_cal:, i], factor)
            row["calibrated_coverage_test"] = metrics.coverage(y_all[n_cal:, i], lo, hi)
        out.append(row)
    return out
