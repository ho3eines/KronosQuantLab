"""Forecast error metrics. All functions take plain arrays and are model-agnostic.

Definitions (y = realised value, f = forecast, mean over all supplied elements):

* MAE   = mean(|y - f|)
* RMSE  = sqrt(mean((y - f)^2))
* sMAPE = 100 * mean( 2|y - f| / (|y| + |f|) ), range 0..200 (percent).
  A term whose denominator is below ``eps`` (both values ~0) counts as 0: a
  forecast of ~0 for a value of ~0 is a perfect forecast, not an undefined one.
* coverage = share of realised values with lower <= y <= upper (bounds inclusive).
"""
from __future__ import annotations

import numpy as np

QUANTILES = (0.10, 0.50, 0.90)


def _pair(y: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    if y.shape != f.shape:
        raise ValueError(f"shape mismatch: {y.shape} vs {f.shape}")
    if y.size == 0:
        raise ValueError("empty input")
    if not (np.isfinite(y).all() and np.isfinite(f).all()):
        raise ValueError("non-finite values in metric input")
    return y, f


def mae(y: np.ndarray, f: np.ndarray) -> float:
    y, f = _pair(y, f)
    return float(np.mean(np.abs(y - f)))


def rmse(y: np.ndarray, f: np.ndarray) -> float:
    y, f = _pair(y, f)
    return float(np.sqrt(np.mean((y - f) ** 2)))


def smape(y: np.ndarray, f: np.ndarray, eps: float = 1e-12) -> float:
    y, f = _pair(y, f)
    denom = np.abs(y) + np.abs(f)
    terms = np.zeros_like(denom)
    np.divide(2.0 * np.abs(y - f), denom, out=terms, where=denom > eps)
    return float(100.0 * np.mean(terms))


def path_quantiles(paths: np.ndarray, qs: tuple[float, ...] = QUANTILES) -> np.ndarray:
    """``paths`` has the sample axis first; returns ``(len(qs), ...)``."""
    paths = np.asarray(paths, dtype=np.float64)
    if paths.shape[0] < 2:
        raise ValueError("at least 2 sample paths are needed for quantiles")
    return np.quantile(paths, qs, axis=0)


def coverage(y: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    y, lower = _pair(y, lower)
    _, upper = _pair(y, upper)
    return float(np.mean((y >= lower) & (y <= upper)))
