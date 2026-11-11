"""Forecaster contract and leak-free window construction."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from app.core.config import FEATURE_COLUMNS
from app.core.errors import DataValidationError, ForecastError


class Forecaster(Protocol):
    """Anything that can draw sample paths for the next ``len(future_ts)`` bars."""

    name: str

    def sample_paths(
        self, context: pd.DataFrame, future_ts: pd.Series, n_paths: int, seed: int
    ) -> np.ndarray:
        """Return float array ``(n_paths, len(future_ts), 6)`` in FEATURE_COLUMNS order."""
        ...


@dataclass(frozen=True)
class Window:
    context: pd.DataFrame  # rows strictly before the forecast origin
    future_ts: pd.Series  # tz-naive UTC timestamps of the bars to predict
    actual: pd.DataFrame | None  # realised bars; never handed to a forecaster


def to_naive_utc(ts: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts, utc=True)
    return ts.dt.tz_localize(None)


def make_window(
    df: pd.DataFrame, origin: int, lookback: int, horizon: int, freq: str = "1D"
) -> Window:
    """Context = rows ``[origin-lookback, origin)``; targets = rows ``[origin, origin+horizon)``.

    ``origin == len(df)`` is allowed (true out-of-sample forecast, ``actual=None``).
    """
    if lookback <= 0 or horizon <= 0:
        raise DataValidationError("lookback and horizon must be positive")
    if origin - lookback < 0 or origin > len(df):
        raise DataValidationError(f"origin {origin} with lookback {lookback} is outside the data")
    context = df.iloc[origin - lookback: origin].reset_index(drop=True)
    step = pd.Timedelta(freq)
    ts = pd.to_datetime(context["timestamp"], utc=True)
    if not (ts.diff().dropna() == step).all():
        raise DataValidationError("context window is not contiguous and strictly increasing")
    if context[list(FEATURE_COLUMNS)].isnull().values.any():
        raise DataValidationError("context window contains nulls")
    future = pd.Series(pd.date_range(ts.iloc[-1] + step, periods=horizon, freq=step))
    actual = None
    if origin + horizon <= len(df):
        actual = df.iloc[origin: origin + horizon].reset_index(drop=True)
        if not (pd.to_datetime(actual["timestamp"], utc=True).reset_index(drop=True) == future).all():
            raise DataValidationError("target window does not line up with forecast timestamps")
    return Window(context=context, future_ts=to_naive_utc(future), actual=actual)


def check_paths(paths: np.ndarray, n_paths: int, horizon: int) -> np.ndarray:
    """Enforce the output contract so a misbehaving model fails loudly, not silently."""
    arr = np.asarray(paths, dtype=np.float64)
    expected = (n_paths, horizon, len(FEATURE_COLUMNS))
    if arr.shape != expected:
        raise ForecastError(f"forecast shape {arr.shape} != expected {expected}")
    if not np.isfinite(arr).all():
        raise ForecastError("forecast contains NaN or infinite values")
    return arr
