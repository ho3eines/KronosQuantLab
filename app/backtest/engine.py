"""P4: walk-forward backtest of the research rules, long-only, single asset.

Timing (the look-ahead control):
  * a decision is made after the close of bar t using bars 0..t only;
  * it is executed at the OPEN of bar t+1, with slippage and fee;
  * equity is marked at each bar's close.
A backtest result describes the past under these assumptions. It is not a
forecast of future performance and not evidence of profitability.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.execution import Costs, rebalance
from app.core.config import TRADING_DAYS_PER_YEAR
from app.core.errors import DataValidationError, KQLError, require
from app.forecast.base import Forecaster
from app.signals.pipeline import decide_at
from app.signals.regime import RegimeParams
from app.signals.rules import ABSTAIN, SignalParams

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    lookback: int = 400
    n_paths: int = 20
    rebalance_every: int = 7  # bars between decisions
    n_decisions: int = 26  # decisions are taken from the END of the data backwards
    initial_cash: float = 10_000.0
    seed: int = 20260101
    costs: Costs = Costs()

    def __post_init__(self) -> None:
        for name in ("lookback", "rebalance_every", "n_decisions"):
            require(getattr(self, name) >= 1, f"{name} must be at least 1")
        require(self.n_paths >= 2, "n_paths must be at least 2 (quantiles need several paths)")
        require(math.isfinite(self.initial_cash) and self.initial_cash > 0, "initial_cash must be positive")


@dataclass
class BacktestResult:
    equity: pd.DataFrame  # timestamp, equity, buy_hold, position_fraction
    decisions: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    metrics: dict[str, dict[str, float | int | None]]
    errors: list[dict[str, Any]]


def performance(equity: np.ndarray) -> dict[str, float | None]:
    """Standard summary of a daily equity curve (risk-free rate 0, 365 days/year)."""
    eq = np.asarray(equity, dtype=np.float64)
    if len(eq) < 2:
        return {"total_return": 0.0, "cagr": None, "annual_vol": None, "sharpe": None, "max_drawdown": 0.0}
    rets = eq[1:] / eq[:-1] - 1.0
    total = float(eq[-1] / eq[0] - 1.0)
    years = (len(eq) - 1) / TRADING_DAYS_PER_YEAR
    vol = float(np.std(rets, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(rets) > 1 else None
    sharpe = float(np.mean(rets) * TRADING_DAYS_PER_YEAR / vol) if vol else None
    drawdown = float(np.min(eq / np.maximum.accumulate(eq) - 1.0))
    cagr = float((eq[-1] / eq[0]) ** (1 / years) - 1.0) if years > 0 and eq[-1] > 0 else None
    return {"total_return": total, "cagr": cagr, "annual_vol": vol, "sharpe": sharpe, "max_drawdown": drawdown}


def decision_indices(n_rows: int, cfg: BacktestConfig, min_history: int) -> list[int]:
    last = n_rows - 2  # the decision at the last bar could not be executed inside the data
    idx = sorted(last - k * cfg.rebalance_every for k in range(cfg.n_decisions))
    idx = [t for t in idx if t + 1 >= min_history]
    if not idx:
        raise DataValidationError(f"{n_rows} rows are not enough history for a backtest (need {min_history}+)")
    return idx


def run_backtest(
    df: pd.DataFrame, forecaster: Forecaster, params: SignalParams, cfg: BacktestConfig = BacktestConfig(),
    regime_params: RegimeParams = RegimeParams(),
) -> BacktestResult:
    df = df.reset_index(drop=True)
    min_history = max(regime_params.min_bars, 30)
    decide_on = decision_indices(len(df), cfg, min_history)
    start = decide_on[0] + 1  # first bar on which anything can be executed
    cash, qty = cfg.initial_cash, 0.0
    bh_fill = rebalance(cfg.initial_cash, 0.0, float(df["open"].iloc[start]), 1.0, cfg.costs)
    pending: float | None = None
    rows, decisions, trades, errors = [], [], [], []
    fees = 0.0
    decide_set = set(decide_on)

    def make_decision(t: int) -> float | None:
        try:
            ctx = decide_at(df, t, forecaster, params, cfg.lookback, cfg.n_paths, cfg.seed, regime_params)
        except KQLError as exc:  # a failed forecast means "do nothing", never a crash
            log.error("decision at row %d failed: %s", t, exc)
            errors.append({"row": t, "timestamp": str(df["timestamp"].iloc[t]), "error": str(exc)})
            return None
        d = ctx.decision
        decisions.append({"timestamp": str(ctx.decision_ts), "action": d.action, "target_fraction": d.target_fraction,
                          "r10": d.r10, "r50": d.r50, "r90": d.r90, "trend": ctx.regime.trend,
                          "volatility": ctx.regime.volatility, "reasons": "; ".join(d.reasons)})
        return None if d.action == ABSTAIN else d.target_fraction

    pending = make_decision(decide_on[0])
    for i in range(start, len(df)):
        o, c = float(df["open"].iloc[i]), float(df["close"].iloc[i])
        if pending is not None:
            fill = rebalance(cash, qty, o, pending, cfg.costs)
            if fill.qty_delta != 0.0:
                trades.append({"timestamp": str(df["timestamp"].iloc[i]), "side": "BUY" if fill.qty_delta > 0 else "SELL",
                               "qty": abs(fill.qty_delta), "price": fill.price, "fee": fill.fee})
                fees += fill.fee
            cash, qty = fill.cash, fill.qty
            pending = None
        equity = cash + qty * c
        rows.append({"timestamp": df["timestamp"].iloc[i], "equity": equity, "buy_hold": bh_fill.cash + bh_fill.qty * c,
                     "position_fraction": (qty * c / equity) if equity > 0 else 0.0})
        if i in decide_set and i < len(df) - 1:
            pending = make_decision(i)

    eq = pd.DataFrame(rows)
    base = np.concatenate([[cfg.initial_cash], eq["equity"].to_numpy()])
    bh = np.concatenate([[cfg.initial_cash], eq["buy_hold"].to_numpy()])
    strat: dict[str, Any] = performance(base)
    strat.update(n_trades=len(trades), fees_paid=fees, mean_exposure=float(eq["position_fraction"].mean()),
                 n_decisions=len(decisions), n_failed_decisions=len(errors), n_bars=len(eq))
    return BacktestResult(eq, decisions, trades, {"strategy": strat, "buy_and_hold": performance(bh),
                                                  "cash": {"total_return": 0.0, "max_drawdown": 0.0}}, errors)


def config_dict(cfg: BacktestConfig, params: SignalParams) -> dict[str, Any]:
    return {"backtest": asdict(cfg), "signal": asdict(params)}
