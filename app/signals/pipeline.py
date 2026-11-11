"""Forecast + regime -> decision, for one decision bar. Shared by backtest and paper simulator."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.errors import DataValidationError
from app.forecast.base import Forecaster
from app.forecast.service import Forecast, make_forecast
from app.signals.regime import Regime, RegimeParams, detect_regime
from app.signals.rules import Decision, SignalParams, decide


@dataclass(frozen=True)
class DecisionContext:
    decision_ts: pd.Timestamp
    forecast: Forecast
    regime: Regime
    decision: Decision


def decide_at(
    df: pd.DataFrame, t: int, forecaster: Forecaster, params: SignalParams, lookback: int, n_paths: int,
    base_seed: int = 20260101, regime_params: RegimeParams = RegimeParams(),
) -> DecisionContext:
    """Decision after the close of row ``t`` using rows ``0..t`` only."""
    if t < 0 or t >= len(df):
        raise DataValidationError(f"decision index {t} outside the data")
    past = df.iloc[: t + 1]  # the single place where history is cut; everything below sees only this
    fc = make_forecast(past, forecaster, lookback, params.horizon, n_paths, base_seed)
    regime = detect_regime(past["close"], regime_params)
    i = params.horizon - 1
    decision = decide(float(fc.p10[i]), float(fc.p50[i]), float(fc.p90[i]), fc.last_close, regime, params)
    return DecisionContext(pd.Timestamp(past["timestamp"].iloc[-1]), fc, regime, decision)
