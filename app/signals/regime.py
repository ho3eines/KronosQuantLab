"""P3: market regime from PAST closes only (trend x volatility). Research tool, not advice.

``regime_series`` computes the regime of *every* bar from data up to that bar.  It is
the single implementation behind ``detect_regime`` (last bar) and the threshold
validation in ``app/signals/validation.py`` (labels for Adjusted Rand Index tests).
Every value at bar *i* depends only on bars ``0..i``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core import config, timeframes
from app.core.errors import DataValidationError, require

TREND, VOLATILITY = "trend", "volatility"


@dataclass(frozen=True)
class RegimeParams:
    trend_window: int = 50  # SMA length
    slope_lag: int = 10  # SMA now vs SMA this many bars ago
    vol_window: int = 30  # realised-volatility window
    vol_history: int = 365  # how far back current volatility is ranked
    low_pct: float = 0.25
    high_pct: float = 0.75

    def __post_init__(self) -> None:
        for name in ("trend_window", "slope_lag", "vol_window", "vol_history"):
            require(getattr(self, name) >= 2, f"{name} must be at least 2")
        require(0 <= self.low_pct < self.high_pct <= 1, "need 0 <= low_pct < high_pct <= 1")

    @property
    def min_bars(self) -> int:
        return max(self.trend_window + self.slope_lag, 2 * self.vol_window) + 1


@dataclass(frozen=True)
class Regime:
    trend: str  # up | down | sideways
    volatility: str  # low | normal | high
    realized_vol_annual: float
    vol_percentile: float
    close_vs_sma: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_close(close: pd.Series | np.ndarray, params: RegimeParams) -> pd.Series:
    c = pd.Series(np.asarray(close, dtype=np.float64)).reset_index(drop=True)
    if len(c) < params.min_bars:
        raise DataValidationError(f"regime needs at least {params.min_bars} bars, got {len(c)}")
    if not (np.isfinite(c).all() and (c > 0).all()):
        raise DataValidationError("regime needs finite, positive closes")
    return c


def regime_series(
    close: pd.Series, params: RegimeParams = RegimeParams(), bars_per_year: float | None = None,
    interval: str | None = None,
) -> pd.DataFrame:
    """Causal regime labels for every bar.

    Columns: ``trend``, ``volatility`` (None until the windows are full),
    ``realized_vol_annual``, ``vol_percentile``, ``close_vs_sma`` and ``valid``.
    """
    c = _check_close(close, params)
    bpy = float(bars_per_year if bars_per_year is not None else timeframes.bars_per_year(interval or config.INTERVAL))
    sma = c.rolling(params.trend_window).mean()
    sma_then = sma.shift(params.slope_lag)
    trend = pd.Series(
        np.select([(c > sma) & (sma > sma_then), (c < sma) & (sma < sma_then)], ["up", "down"], default="sideways"),
        index=c.index, dtype=object,
    )
    vol = np.log(c).diff().rolling(params.vol_window).std() * np.sqrt(bpy)
    # mid-rank (average) within the trailing window: a constant-volatility series
    # ranks 0.5 ("normal"), never 1.0.
    pct = vol.rolling(params.vol_history, min_periods=1).rank(pct=True, method="average")
    level = pd.Series(
        np.select([pct <= params.low_pct, pct >= params.high_pct], ["low", "high"], default="normal"),
        index=c.index, dtype=object,
    )
    valid = sma.notna() & sma_then.notna() & vol.notna() & pct.notna()
    return pd.DataFrame({
        "trend": trend.where(valid),
        "volatility": level.where(valid),
        "realized_vol_annual": vol,
        "vol_percentile": pct,
        "close_vs_sma": c / sma - 1.0,
        "valid": valid,
    })


def regime_labels(
    close: pd.Series, params: RegimeParams = RegimeParams(), bars_per_year: float | None = None,
    interval: str | None = None,
) -> pd.Series:
    """One string label per bar (``trend|volatility``), None where the windows are not full."""
    table = regime_series(close, params, bars_per_year, interval)
    labels = table["trend"].astype(str) + "|" + table["volatility"].astype(str)
    return labels.where(table["valid"])


def detect_regime(
    close: pd.Series, params: RegimeParams = RegimeParams(), bars_per_year: float | None = None,
    interval: str | None = None,
) -> Regime:
    """``close`` must end at the decision bar; nothing after it may be passed in."""
    table = regime_series(close, params, bars_per_year, interval)
    last = table.iloc[-1]
    if not bool(last["valid"]):  # defensive: _check_close guarantees this for min_bars
        raise DataValidationError("regime is undefined at the last bar")
    return Regime(
        str(last["trend"]), str(last["volatility"]), float(last["realized_vol_annual"]),
        float(last["vol_percentile"]), float(last["close_vs_sma"]),
    )
