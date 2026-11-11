"""Forecaster contract and leak-free window construction."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from app.core.config import FEATURE_COLUMNS, MAX_CONTEXT, MAX_HORIZON
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


def infer_step(timestamps: pd.Series) -> pd.Timedelta:
    """Smallest positive spacing of the timestamps (the candle step).

    The smallest spacing is deliberate: a missing bar must look like a gap, not like
    a weekly series.  Falls back to one day when there is nothing to measure.
    """
    ts = pd.to_datetime(timestamps, utc=True)
    deltas = ts.diff().dropna()
    deltas = deltas[deltas > pd.Timedelta(0)]
    return deltas.min() if not deltas.empty else pd.Timedelta(days=1)


def make_window(
    df: pd.DataFrame, origin: int, lookback: int, horizon: int, freq: str | None = None
) -> Window:
    """Context = rows ``[origin-lookback, origin)``; targets = rows ``[origin, origin+horizon)``.

    ``origin == len(df)`` is allowed (true out-of-sample forecast, ``actual=None``).
    ``freq=None`` infers the candle step from the context timestamps, so hourly,
    4-hour and daily data all work without threading the interval through.
    """
    if lookback <= 0 or horizon <= 0:
        raise DataValidationError("lookback and horizon must be positive")
    if lookback > MAX_CONTEXT:
        raise DataValidationError(f"lookback {lookback} exceeds the model maximum of {MAX_CONTEXT} bars")
    if horizon > MAX_HORIZON:
        raise DataValidationError(f"horizon {horizon} exceeds MAX_HORIZON={MAX_HORIZON} bars")
    if origin - lookback < 0 or origin > len(df):
        raise DataValidationError(f"origin {origin} with lookback {lookback} is outside the data")
    context = df.iloc[origin - lookback: origin].reset_index(drop=True)
    ts = pd.to_datetime(context["timestamp"], utc=True)
    step = pd.Timedelta(freq) if freq is not None else infer_step(ts)
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
