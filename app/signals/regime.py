"""P3: market regime from PAST closes only (trend x volatility). Research tool, not advice."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import TRADING_DAYS_PER_YEAR
from app.core.errors import DataValidationError


@dataclass(frozen=True)
class RegimeParams:
    trend_window: int = 50  # SMA length
    slope_lag: int = 10  # SMA now vs SMA this many bars ago
    vol_window: int = 30  # realised-volatility window
    vol_history: int = 365  # how far back current volatility is ranked
    low_pct: float = 0.25
    high_pct: float = 0.75

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


def detect_regime(close: pd.Series, params: RegimeParams = RegimeParams()) -> Regime:
    """``close`` must end at the decision bar; nothing after it may be passed in."""
    c = pd.Series(np.asarray(close, dtype=np.float64))
    if len(c) < params.min_bars:
        raise DataValidationError(f"regime needs at least {params.min_bars} bars, got {len(c)}")
    sma = c.rolling(params.trend_window).mean()
    above = c.iloc[-1] > sma.iloc[-1]
    rising = sma.iloc[-1] > sma.iloc[-1 - params.slope_lag]
    trend = "up" if (above and rising) else "down" if (not above and not rising) else "sideways"
    vol = np.log(c).diff().rolling(params.vol_window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    hist = vol.dropna().iloc[-params.vol_history:]
    current = float(hist.iloc[-1])
    # mid-rank, so a series with constant volatility ranks 0.5 ("normal"), not 1.0
    equal = np.isclose(hist, current, rtol=1e-9, atol=1e-12)
    pct = float(((hist < current) & ~equal).mean() + 0.5 * equal.mean())
    level = "low" if pct <= params.low_pct else "high" if pct >= params.high_pct else "normal"
    return Regime(trend, level, current, pct, float(c.iloc[-1] / sma.iloc[-1] - 1.0))
