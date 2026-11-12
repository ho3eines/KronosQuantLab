"""P4: cross-sectional (Qlib ``TopkDropout``-style) portfolio simulation.

Long-only spot, no leverage, no shorting.  Every symbol is scored at a decision bar
by the *median* (P50) forecast return over ``horizon`` bars; the portfolio then

* **holds** the ``n_symbol_hold`` best-scoring symbols,
* **sells** at most ``n_symbol_drop`` of the worst-scoring holdings that have been
  held for at least ``hold_thresh`` bars (the minimum holding period),
* **buys** the best-scoring symbols that are not held yet, with equal weights
  ``1 / n_effective_hold``.

Timing is the same as the single-asset backtest: a decision is made after the
close of bar *t* using bars ``0..t`` of every symbol only, and executed at the
OPEN of bar *t+1* with fee and slippage.  Labels are for research; this is not a
trading system and the output is not a forecast of profit.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.engine import performance
from app.backtest.execution import Costs
from app.core import config, timeframes
from app.core.errors import ConfigError, DataValidationError, KQLError, require
from app.forecast.base import Forecaster
from app.forecast.service import make_forecast

log = logging.getLogger(__name__)
REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "amount")
EPS = 1e-12


@dataclass(frozen=True)
class PortfolioConfig:
    """Simulation knobs. Defaults follow the documented Qlib-style portfolio settings."""

    n_symbol_hold: int = config.PORTFOLIO_DEFAULTS.n_symbol_hold
    n_symbol_drop: int = config.PORTFOLIO_DEFAULTS.n_symbol_drop
    hold_thresh: int = config.PORTFOLIO_DEFAULTS.hold_thresh
    initial_cash: float = config.PORTFOLIO_DEFAULTS.account
    lookback: int = config.LOOKBACK
    horizon: int = 7
    n_paths: int = config.DEFAULT_SAMPLE_COUNT
    rebalance_every: int = 1
    interval: str = config.INTERVAL
    calendar: str = "24/7"  # all symbols of one portfolio share a venue calendar
    bars_per_year: float | None = None
    time_range: tuple[str | None, str | None] = (None, None)
    seed: int = 20260101
    costs: Costs = field(default_factory=Costs)

    def __post_init__(self) -> None:
        require(self.n_symbol_hold >= 1, "n_symbol_hold must be at least 1")
        require(1 <= self.n_symbol_drop, "n_symbol_drop must be at least 1")
        require(self.n_symbol_drop <= self.n_symbol_hold, "n_symbol_drop cannot exceed n_symbol_hold")
        require(self.hold_thresh >= 0, "hold_thresh must not be negative")
        require(1 <= self.lookback <= config.MAX_CONTEXT, f"lookback must be between 1 and {config.MAX_CONTEXT}")
        require(1 <= self.horizon <= config.MAX_HORIZON, f"horizon must be between 1 and {config.MAX_HORIZON}")
        require(self.n_paths >= 2, "n_paths must be at least 2 (quantiles need several paths)")
        require(self.rebalance_every >= 1, "rebalance_every must be at least 1")
        require(math.isfinite(self.initial_cash) and self.initial_cash > 0, "initial_cash must be positive")
        timeframes.normalize(self.interval)
        require(self.calendar in ("24/7", "fx"), f"unknown calendar '{self.calendar}'")
        require(self.bars_per_year is None or self.bars_per_year > 0, "bars_per_year must be positive")
        start, end = self.start, self.end
        if start is not None and end is not None:
            require(start < end, "time_range start must be before end")

    def _stamp(self, value: str | None) -> pd.Timestamp | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            ts = pd.Timestamp(value.strip())
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"invalid time_range value {value!r}: {exc}") from exc
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    @property
    def start(self) -> pd.Timestamp | None:
        return self._stamp(self.time_range[0])

    @property
    def end(self) -> pd.Timestamp | None:
        return self._stamp(self.time_range[1])

    @property
    def annualisation(self) -> float:
        return float(self.bars_per_year or timeframes.bars_per_year(self.interval))


@dataclass(frozen=True)
class PortfolioFill:
    cash: float
    positions: dict[str, float]
    trades: list[dict[str, Any]]
    fees: float

    @property
    def traded_notional(self) -> float:
        return float(sum(t["qty"] * t["price"] for t in self.trades))


@dataclass
class PortfolioResult:
    equity: pd.DataFrame  # timestamp, equity, equal_weight, exposure, n_positions, cash
    decisions: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    metrics: dict[str, dict[str, float | int | None]]
    errors: list[dict[str, Any]]
    effective_hold: int


def _check_frame(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"{symbol}: missing columns {missing}")
    if df.empty:
        raise DataValidationError(f"{symbol}: no candles")
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="last")
    prices = out[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise DataValidationError(f"{symbol}: prices must be finite and positive")
    return out.reset_index(drop=True)


def align_universe(data: dict[str, pd.DataFrame]) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    """Restrict every symbol to the timestamps they all share (an inner join)."""
    if len(data) < 2:
        raise DataValidationError("a portfolio backtest needs at least two symbols")
    frames = {symbol: _check_frame(symbol, df) for symbol, df in data.items()}
    common: set[pd.Timestamp] | None = None
    for frame in frames.values():
        stamps = set(frame["timestamp"])
        common = stamps if common is None else common & stamps
    calendar = pd.DatetimeIndex(sorted(common or set()))
    if len(calendar) < 3:
        raise DataValidationError("the symbols share fewer than 3 timestamps: check the stored data")
    restricted = {s: f[f["timestamp"].isin(calendar)].reset_index(drop=True) for s, f in frames.items()}
    for s, f in restricted.items():
        if len(f) != len(calendar):  # pragma: no cover - guaranteed by construction
            raise DataValidationError(f"{s}: could not align to the common calendar")
    return calendar, restricted


def rebalance_portfolio(
    cash: float, positions: dict[str, float], prices: dict[str, float], weights: dict[str, float],
    costs: Costs,
) -> PortfolioFill:
    """Move the portfolio towards ``weights`` at ``prices``; sells first, then buys.

    Long-only and unleveraged: target weights are clamped to ``[0, 1]`` and a buy
    can never spend more cash than is available after paying the fee.  Symbols
    without a usable price are left untouched.  Trades below
    ``costs.min_trade_fraction`` of equity are ignored, exactly like the
    single-asset ``rebalance``.
    """
    positions = {s: q for s, q in positions.items() if q > EPS}
    equity = cash + sum(q * prices[s] for s, q in positions.items() if s in prices)
    if equity <= 0:
        return PortfolioFill(cash, positions, [], 0.0)
    targets = {s: min(max(float(w), 0.0), 1.0) for s, w in weights.items() if w > 0 and s in prices}
    fee_rate = costs.fee_bps / 1e4
    slip = costs.slippage_bps / 1e4
    trades: list[dict[str, Any]] = []
    fees = 0.0
    sells: list[tuple[float, str, float]] = []
    buys: list[tuple[float, str]] = []
    for symbol in sorted(set(positions) | set(targets)):
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        qty = positions.get(symbol, 0.0)
        delta_value = targets.get(symbol, 0.0) * equity - qty * price
        if abs(delta_value) < costs.min_trade_fraction * equity:
            continue
        if delta_value > 0:
            buys.append((delta_value, symbol))
        else:
            sells.append((-delta_value, symbol, min(-delta_value / price, qty)))
    sells.sort(key=lambda item: item[0], reverse=True)
    for _, symbol, dq in sells:
        if dq <= EPS:
            continue
        price = prices[symbol]
        fill_price = price * (1 - slip)
        proceeds = dq * fill_price
        fee = proceeds * fee_rate
        cash += proceeds - fee
        fees += fee
        positions[symbol] = positions.get(symbol, 0.0) - dq
        trades.append({"symbol": symbol, "side": "SELL", "qty": dq, "price": fill_price, "fee": fee})
    buys.sort(key=lambda item: item[0], reverse=True)
    for target_value, symbol in buys:
        price = prices[symbol]
        current_value = positions.get(symbol, 0.0) * price
        spend = min(target_value - current_value, cash / (1 + fee_rate))
        if spend <= EPS:
            continue
        fill_price = price * (1 + slip)
        dq = spend / fill_price
        fee = spend * fee_rate
        cash -= spend + fee
        fees += fee
        positions[symbol] = positions.get(symbol, 0.0) + dq
        trades.append({"symbol": symbol, "side": "BUY", "qty": dq, "price": fill_price, "fee": fee})
    positions = {s: q for s, q in positions.items() if q > EPS}
    return PortfolioFill(max(cash, 0.0), positions, trades, fees)


def score_symbols(
    frames: dict[str, pd.DataFrame], t: int, forecaster: Forecaster, cfg: PortfolioConfig,
    decision_ts: pd.Timestamp,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Median forecast return over ``horizon`` bars for every symbol, using bars ``0..t``."""
    scores: dict[str, float] = {}
    errors: list[dict[str, Any]] = []
    for symbol, frame in frames.items():
        past = frame.iloc[: t + 1]
        try:
            fc = make_forecast(past, forecaster, cfg.lookback, cfg.horizon, cfg.n_paths, cfg.seed,
                               interval=cfg.interval, calendar=cfg.calendar)
            scores[symbol] = float(fc.p50[-1]) / fc.last_close - 1.0
        except KQLError as exc:  # one failing symbol must not stop the portfolio
            log.error("%s: forecast at %s failed: %s", symbol, decision_ts, exc)
            errors.append({"symbol": symbol, "timestamp": str(decision_ts), "error": str(exc)})
    return scores, errors


def select_targets(
    scores: dict[str, float], held: dict[str, int], t: int, cfg: PortfolioConfig
) -> tuple[list[str], list[str], list[str], int]:
    """Qlib TopkDropout-style selection. Returns ``(targets, sells, buys, effective_hold)``.

    ``held`` maps symbol -> bar index at which it was bought.  Every current holding
    stays in the target unless it is explicitly sold; a holding younger than
    ``hold_thresh`` bars is never sold voluntarily, so a full portfolio may have to
    wait before it can rotate into better names.  If the universe shrank so much
    that more than ``effective_hold`` names must go, the worst ones are still sold
    (the position cap has priority over the minimum holding period).
    """
    ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
    effective = min(cfg.n_symbol_hold, len(ranked))
    if effective == 0:
        return [], [], [], 0
    top_set = set(ranked[:effective])
    target = sorted(held, key=lambda s: scores.get(s, -math.inf), reverse=True)
    sellable = [s for s in held if s not in top_set and (t - held[s]) >= cfg.hold_thresh]
    sellable.sort(key=lambda s: scores.get(s, -math.inf))
    sells = sellable[: cfg.n_symbol_drop]
    target = [s for s in target if s not in sells]
    if len(target) > effective:  # the universe shrank: trim the worst, regardless of age
        extra = sorted(target, key=lambda s: scores.get(s, -math.inf))[: len(target) - effective]
        sells.extend(extra)
        target = [s for s in target if s not in extra]
    buys: list[str] = []
    for symbol in ranked:
        if len(target) >= effective:
            break
        if symbol not in target and symbol not in sells:
            target.append(symbol)
            buys.append(symbol)
    return target, sells, buys, effective


def run_portfolio_backtest(
    data: dict[str, pd.DataFrame], forecaster: Forecaster, cfg: PortfolioConfig = PortfolioConfig()
) -> PortfolioResult:
    """Walk-forward portfolio simulation over an aligned multi-symbol universe."""
    calendar, frames = align_universe(data)
    start, end = cfg.start, cfg.end
    first_in_range = int(calendar.searchsorted(start)) if start is not None else 0
    last_exclusive = int(calendar.searchsorted(end, side="right")) if end is not None else len(calendar)
    first_decision = max(first_in_range, cfg.lookback)
    if first_decision >= last_exclusive - 1:
        raise DataValidationError(
            f"not enough aligned bars: need lookback={cfg.lookback} before the first execution inside the range"
        )
    decide_on = set(range(first_decision, last_exclusive - 1, cfg.rebalance_every))
    first_exec = min(decide_on) + 1
    bars_per_year = cfg.annualisation
    effective_hold = min(cfg.n_symbol_hold, len(frames))

    cash: float = float(cfg.initial_cash)
    qty: dict[str, float] = {}
    entry: dict[str, int] = {}  # symbol -> bar index at which the position was opened
    pending: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    fees_paid = 0.0
    turnovers: list[float] = []

    bench_cash: float = float(cfg.initial_cash)
    bench_positions: dict[str, float] = {}
    bench_started = False

    def prices_at(i: int, column: str) -> dict[str, float]:
        return {s: float(f[column].iloc[i]) for s, f in frames.items()}

    for i in range(first_exec, last_exclusive):
        opens = prices_at(i, "open")
        if pending is not None:
            fill = rebalance_portfolio(cash, qty, opens, pending["weights"], cfg.costs)
            cash = fill.cash
            for symbol, new_qty in fill.positions.items():
                if new_qty > qty.get(symbol, 0.0) + EPS and symbol not in qty:
                    entry[symbol] = i  # a newly opened position starts its holding period here
            qty = dict(fill.positions)
            entry = {s: k for s, k in entry.items() if s in qty}
            fees_paid += fill.fees
            turnovers.append(fill.traded_notional)
            for trade in fill.trades:
                trades.append({"timestamp": str(calendar[i]), **trade})
            pending["fills"] = fill.trades
            pending = None
        if not bench_started:
            bench_weights = {s: 1.0 / len(frames) for s in frames}
            # the benchmark has no rebalancing churn, so the minimum-trade filter must not
            # silently leave a large universe in cash (weight 1/n can be below the filter)
            bench_costs = replace(cfg.costs, min_trade_fraction=0.0)
            bench_fill = rebalance_portfolio(bench_cash, bench_positions, opens, bench_weights, bench_costs)
            bench_cash, bench_positions = bench_fill.cash, bench_fill.positions
            bench_started = True

        closes = prices_at(i, "close")
        equity = cash + sum(q * closes[s] for s, q in qty.items())
        benchmark = bench_cash + sum(q * closes[s] for s, q in bench_positions.items())
        rows.append({
            "timestamp": calendar[i], "equity": equity, "equal_weight": benchmark,
            "exposure": (equity - cash) / equity if equity > 0 else 0.0,
            "n_positions": len(qty), "cash": cash,
        })
        if i in decide_on:
            decision_ts = calendar[i]
            scores, score_errors = score_symbols(frames, i, forecaster, cfg, decision_ts)
            errors.extend(score_errors)
            targets, sells, buys, effective_hold = select_targets(scores, entry, i, cfg)
            weights = {s: 1.0 / len(targets) for s in targets} if targets else {}
            decisions.append({
                "timestamp": str(decision_ts), "targets": targets, "weights": weights,
                "sells": sells, "buys": buys, "n_scores": len(scores),
                "n_failed": len(score_errors),
                "scores": {s: scores[s] for s in targets if s in scores},
            })
            pending = {"weights": weights, "sells": sells, "buys": buys, "fills": []}
        log.debug("bar %d/%d equity %.2f", i, last_exclusive - 1, equity)

    equity_df = pd.DataFrame(rows).reset_index(drop=True)
    if equity_df.empty:
        raise DataValidationError("the simulation produced no bars")
    strategy = performance(equity_df["equity"].to_numpy(), bars_per_year)
    strategy.update(
        n_trades=len(trades), fees_paid=fees_paid, n_rebalances=len(decisions),
        n_failed_decisions=len(errors), mean_exposure=float(equity_df["exposure"].mean()),
        max_positions=int(equity_df["n_positions"].max()), n_symbols=len(frames),
        effective_hold=effective_hold, mean_turnover=float(np.mean(turnovers)) if turnovers else 0.0,
        n_bars=len(equity_df),
    )
    benchmark_metrics = performance(equity_df["equal_weight"].to_numpy(), bars_per_year)
    benchmark_metrics["n_symbols"] = len(frames)
    return PortfolioResult(
        equity=equity_df, decisions=decisions, trades=trades,
        metrics={"strategy": strategy, "equal_weight_universe": benchmark_metrics},
        errors=errors, effective_hold=effective_hold,
    )


def config_dict(cfg: PortfolioConfig) -> dict[str, Any]:
    out = asdict(cfg)
    out["time_range"] = [cfg.time_range[0], cfg.time_range[1]]
    out["account"] = cfg.initial_cash  # the documented name of the initial portfolio value
    out["bars_per_year"] = cfg.annualisation
    return out
