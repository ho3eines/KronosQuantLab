"""Qlib-style portfolio simulation: selection rules, fills, timing, ranges and failures."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest.execution import Costs
from app.backtest.portfolio import (
    PortfolioConfig,
    align_universe,
    config_dict,
    rebalance_portfolio,
    run_portfolio_backtest,
    select_targets,
)
from app.core.errors import ConfigError, DataValidationError, ForecastError
from tests.conftest import FakeForecaster


def universe(n: int = 400, symbols: int = 6, drift_step: float = 0.0005) -> dict[str, pd.DataFrame]:
    frames = {}
    for i in range(symbols):
        rng = np.random.default_rng(100 + i)
        close = 100 * np.exp(np.cumsum(rng.normal(drift_step * (i - symbols / 2), 0.02, n)))
        open_ = np.concatenate([[100.0], close[:-1]])
        df = pd.DataFrame({"timestamp": pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC"),
                           "open": open_, "close": close})
        df["high"] = np.maximum(df["open"], df["close"]) * 1.01
        df["low"] = np.minimum(df["open"], df["close"]) * 0.99
        df["volume"] = 10.0
        df["amount"] = df["volume"] * df["close"]
        frames[f"S{i}"] = df
    return frames


SMALL = dict(n_symbol_hold=3, n_symbol_drop=2, hold_thresh=3, lookback=100, horizon=5, n_paths=5,
             initial_cash=1_000_000.0, rebalance_every=5, costs=Costs(10, 5))


# ------------------------------------------------------------------ configuration
def test_portfolio_config_validation():
    PortfolioConfig()  # documented defaults are valid
    for kwargs in ({"n_symbol_hold": 0}, {"n_symbol_drop": 0}, {"n_symbol_drop": 4, "n_symbol_hold": 3},
                   {"hold_thresh": -1}, {"lookback": 0}, {"lookback": 600}, {"horizon": 0},
                   {"horizon": 10_000}, {"n_paths": 1}, {"rebalance_every": 0},
                   {"initial_cash": 0}, {"initial_cash": float("nan")}, {"interval": "5m"}):
        with pytest.raises(ConfigError):
            PortfolioConfig(**kwargs)
    with pytest.raises(ConfigError, match="start must be before end"):
        PortfolioConfig(time_range=("2024-01-02", "2024-01-01"))
    with pytest.raises(ConfigError, match="invalid time_range"):
        PortfolioConfig(time_range=("not-a-date", None))
    assert PortfolioConfig(time_range=("2024-01-01", None)).start.tzinfo is not None
    assert PortfolioConfig().initial_cash == 100_000_000.0
    assert PortfolioConfig().n_symbol_hold == 50 and PortfolioConfig().n_symbol_drop == 5
    assert PortfolioConfig().hold_thresh == 5


# ------------------------------------------------------------------ selection
def test_selection_holds_the_top_names_and_respects_the_holding_period():
    cfg = PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, hold_thresh=5)
    scores = {"A": 0.05, "B": 0.04, "C": 0.03, "D": 0.01}
    targets, sells, buys, effective = select_targets(scores, {}, 100, cfg)
    assert targets == ["A", "B"] and buys == ["A", "B"] and sells == [] and effective == 2

    held = {"C": 90, "D": 80}  # both older than hold_thresh; C ranks above D
    targets, sells, buys, _ = select_targets(scores, held, 100, cfg)
    # one drop slot per rebalance: the worst holding leaves, the best newcomer enters
    assert sells == ["D"] and buys == ["A"] and set(targets) == {"C", "A"}
    assert len(targets) == 2

    young = {"C": 98, "D": 97}  # younger than hold_thresh: not sold voluntarily
    targets, sells, buys, _ = select_targets(scores, young, 100, cfg)
    assert sells == [] and set(targets) == {"C", "D"}


def test_selection_trims_when_the_universe_shrinks():
    cfg = PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, hold_thresh=10)
    scores = {"A": 0.05, "B": 0.04, "C": 0.03}
    held = {"A": 90, "B": 90, "C": 90}
    targets, sells, _, effective = select_targets(scores, held, 100, cfg)
    assert effective == 2 and targets == ["A", "B"] and sells == ["C"]
    # scores shrink to a single symbol: the extra holding must still go
    targets, sells, _, effective = select_targets({"A": 0.05}, held, 100, PortfolioConfig(n_symbol_hold=2,
                                                                                         n_symbol_drop=1))
    assert effective == 1 and targets == ["A"] and len(sells) == 2


# ------------------------------------------------------------------ fills
def test_portfolio_rebalance_sells_first_and_never_leverages_or_overspends():
    costs = Costs(fee_bps=10, slippage_bps=5)
    fill = rebalance_portfolio(1_000_000, {"A": 1000.0}, {"A": 100.0, "B": 50.0}, {"A": 0.0, "B": 1.0}, costs)
    assert fill.positions.get("A", 0.0) == 0.0
    assert fill.positions["B"] > 0 and fill.cash >= 0 and fill.fees > 0
    assert [t["side"] for t in fill.trades][0] == "SELL"  # the sale funds the purchase
    # target weights above 1 are clamped, not levered
    full = rebalance_portfolio(100_000, {}, {"X": 10.0}, {"X": 5.0}, Costs(0, 0, 1.0))
    value = full.positions["X"] * 10.0
    assert value <= 100_000 + 1e-6 and full.cash >= 0
    # a trade below the minimum fraction is ignored
    tiny = rebalance_portfolio(100_000, {}, {"X": 10.0}, {"X": 0.001}, Costs(0, 0, 0.005))
    assert tiny.trades == [] and tiny.cash == 100_000
    # an unusable price leaves the position untouched
    untouched = rebalance_portfolio(1000, {"A": 5.0}, {}, {"A": 0.0}, costs)
    assert untouched.positions == {"A": 5.0} and untouched.cash == 1000


def test_universe_alignment_and_validation():
    frames = universe(symbols=2)
    calendar, aligned = align_universe(frames)
    assert len(calendar) == 400 and all(len(f) == 400 for f in aligned.values())
    with pytest.raises(DataValidationError, match="at least two symbols"):
        align_universe({"A": frames["S0"]})
    broken = frames["S0"].copy()
    broken.loc[5, "close"] = -1.0
    with pytest.raises(DataValidationError, match="finite and positive"):
        align_universe({"A": broken, "B": frames["S1"]})
    with pytest.raises(DataValidationError, match="missing columns"):
        align_universe({"A": frames["S0"].drop(columns="volume"), "B": frames["S1"]})


# ------------------------------------------------------------------ simulation
def test_backtest_executes_at_the_next_open_with_costs():
    data = universe()
    res = run_portfolio_backtest(data, FakeForecaster(), PortfolioConfig(**SMALL))
    first = res.decisions[0]
    decision_ts = pd.Timestamp(first["timestamp"])
    bar = int(data["S0"].index[data["S0"]["timestamp"] == decision_ts][0])
    fill_ts = data["S0"]["timestamp"].iloc[bar + 1]
    trade = [t for t in res.trades if pd.Timestamp(t["timestamp"]) == fill_ts
             and t["symbol"] == first["buys"][0]][0]
    assert trade["price"] == pytest.approx(float(data[first["buys"][0]]["open"].iloc[bar + 1]) * 1.0005)
    assert res.metrics["strategy"]["fees_paid"] > 0
    assert res.equity["n_positions"].max() <= 3
    assert res.equity["cash"].min() >= 0
    assert res.equity["exposure"].max() <= 1.0 + 1e-9
    assert res.metrics["strategy"]["n_trades"] == len(res.trades)
    assert res.metrics["equal_weight_universe"]["n_symbols"] == 6


def test_backtest_has_no_lookahead():
    data = universe()
    cfg = PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, hold_thresh=2, lookback=80, horizon=4, n_paths=4,
                          rebalance_every=7, initial_cash=500_000.0)
    base = run_portfolio_backtest(data, FakeForecaster(), cfg)
    cut = pd.Timestamp(base.decisions[4]["timestamp"])
    tampered = {s: df.copy() for s, df in data.items()}
    for df in tampered.values():
        future = df["timestamp"] > cut
        df.loc[future, ["open", "high", "low", "close"]] *= 4.0
    other = run_portfolio_backtest(tampered, FakeForecaster(), cfg)
    assert base.decisions[:5] == other.decisions[:5]


def test_time_range_limits_the_simulation_but_keeps_the_history():
    data = universe()
    cfg = PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, hold_thresh=1, lookback=60, horizon=3, n_paths=3,
                          rebalance_every=5, time_range=("2022-06-01", "2022-12-01"))
    res = run_portfolio_backtest(data, FakeForecaster(), cfg)
    assert res.equity["timestamp"].min() >= pd.Timestamp("2022-06-01", tz="UTC")
    assert res.equity["timestamp"].max() <= pd.Timestamp("2022-12-01", tz="UTC")
    with pytest.raises(DataValidationError, match="not enough aligned bars"):
        run_portfolio_backtest(data, FakeForecaster(),
                               PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, lookback=300, n_paths=3,
                                               horizon=3, time_range=("2022-06-01", "2022-08-01")))


def test_forecast_failures_are_skipped_never_guessed():
    data = universe(symbols=3)
    cfg = PortfolioConfig(n_symbol_hold=2, n_symbol_drop=1, hold_thresh=1, lookback=80, horizon=3, n_paths=4,
                          rebalance_every=20, initial_cash=100_000.0)
    res = run_portfolio_backtest(data, FakeForecaster(fail_on_call=1), cfg)
    assert len(res.errors) == 1 and res.errors[0]["error"]
    assert res.decisions[0]["n_failed"] == 1 and res.decisions[0]["n_scores"] == 2
    assert all(d["n_scores"] == 3 for d in res.decisions[1:])
    assert res.metrics["strategy"]["n_failed_decisions"] == 1

    class Broken(FakeForecaster):
        def sample_paths(self, *a, **k):
            raise ForecastError("out of memory")

    dead = run_portfolio_backtest(data, Broken(), cfg)
    assert dead.trades == [] and dead.decisions and all(d["targets"] == [] for d in dead.decisions)
    assert len(dead.errors) >= 2


def test_effective_hold_is_clipped_to_the_available_universe():
    data = universe(symbols=2, n=200)
    cfg = PortfolioConfig(n_symbol_hold=50, n_symbol_drop=5, hold_thresh=1, lookback=60, horizon=3, n_paths=3,
                          rebalance_every=10, initial_cash=100_000.0)
    res = run_portfolio_backtest(data, FakeForecaster(), cfg)
    assert res.effective_hold == 2 and res.equity["n_positions"].max() <= 2
    assert res.metrics["strategy"]["effective_hold"] == 2


def test_config_dict_is_plain_json():
    cfg = PortfolioConfig(time_range=("2024-01-01", "2024-06-01"))
    out = config_dict(cfg)
    assert out["time_range"] == ["2024-01-01", "2024-06-01"]
    assert out["n_symbol_hold"] == cfg.n_symbol_hold and out["bars_per_year"] == cfg.annualisation
