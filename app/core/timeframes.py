"""Candle timeframes: the one place that maps an interval to its step and year length.

Supported intervals are ``1h``, ``4h`` and ``1d``.  Everything that needs to know
how long a bar lasts (storage gap checks, forecast horizon timestamps, annualising
volatility) asks this module instead of hard-coding "one day".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.core.errors import ConfigError

DEFAULT_INTERVAL = "1d"
HOURS_PER_YEAR = 365 * 24  # crypto trades every day


@dataclass(frozen=True)
class Timeframe:
    """One supported candle interval."""

    key: str  # the value stored in SQLite and accepted by Binance, e.g. "4h"
    freq: str  # pandas offset alias used for date ranges, e.g. "4h"
    step: pd.Timedelta
    bars_per_year: float
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "step": str(self.step)}


TIMEFRAMES: dict[str, Timeframe] = {
    "1h": Timeframe("1h", "1h", pd.Timedelta(hours=1), float(HOURS_PER_YEAR), "hourly"),
    "4h": Timeframe("4h", "4h", pd.Timedelta(hours=4), float(HOURS_PER_YEAR / 4), "4-hour"),
    "1d": Timeframe("1d", "1D", pd.Timedelta(days=1), 365.0, "daily"),
}
SUPPORTED_INTERVALS: tuple[str, ...] = tuple(TIMEFRAMES)


def normalize(interval: str | None) -> str:
    """Return the canonical interval key or raise a controlled ``ConfigError``."""
    key = (interval or DEFAULT_INTERVAL).strip().lower()
    if key not in TIMEFRAMES:
        raise ConfigError(f"unsupported interval '{interval}'. Supported: {', '.join(SUPPORTED_INTERVALS)}")
    return key


def get(interval: str | None = None) -> Timeframe:
    return TIMEFRAMES[normalize(interval)]


def step(interval: str | None = None) -> pd.Timedelta:
    return get(interval).step


def freq(interval: str | None = None) -> str:
    return get(interval).freq


def bars_per_year(interval: str | None = None) -> float:
    """Number of bars in a year, used to annualise volatility and Sharpe."""
    return get(interval).bars_per_year


def infer_interval(timestamps: Iterable[Any]) -> str | None:
    """Return the interval matching the smallest positive timestamp step, or ``None``.

    The smallest step is used on purpose: a single missing bar must be detected as
    a gap, not silently re-labelled as a coarser interval.
    """
    ts = pd.to_datetime(pd.Series(list(timestamps)), utc=True).dropna().sort_values()
    deltas = ts.diff().dropna()
    deltas = deltas[deltas > pd.Timedelta(0)]
    if deltas.empty:
        return None
    smallest = deltas.min()
    for key, tf in TIMEFRAMES.items():
        if smallest == tf.step:
            return key
    return None


def describe() -> list[dict[str, Any]]:
    """Plain-JSON description of every supported interval (for ``kql.py settings``)."""
    return [tf.as_dict() for tf in TIMEFRAMES.values()]


def bars_between(first: Any, last: Any, interval: str | None = None) -> int:
    """Inclusive number of bars between two timestamps on the given interval grid."""
    delta = pd.Timestamp(last) - pd.Timestamp(first)
    step_ns = int(step(interval).value)
    if step_ns <= 0:
        raise ConfigError("interval step must be positive")
    return int(np.floor(delta.value / step_ns)) + 1
