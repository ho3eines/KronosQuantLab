"""P2 calibration, P3 signals, P4 backtest, P5 paper simulator."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import BacktestConfig, performance, run_backtest
from app.backtest.execution import Costs, rebalance
from app.core.config import FEATURE_COLUMNS
from app.core.errors import DataValidationError, ForecastError
from app.evaluation.calibration import apply_factor, calibrate_split, conformal_factor, interval_scores
from app.paper import simulator
from app.signals.pipeline import decide_at
from app.signals.regime import Regime, RegimeParams, detect_regime
from app.signals.rules import ABSTAIN, BUY, SELL, SignalParams, decide, position_fraction
from app.storage.db import connect
from tests.conftest import FakeForecaster, make_ohlcv


# ---------------------------------------------------------------- calibration
def test_interval_scores_and_factor():
    s = interval_scores(np.array([90.0]), np.array([100.0]), np.array([120.0]), np.array([130.0, 95.0, 100.0]))
    np.testing.assert_allclose(s, [1.5, 0.5, 0.0])
    assert conformal_factor(np.array([0.1, 0.2, 0.3, 0.4, 3.0]), 0.8) == 3.0  # k = ceil(6*0.8) = 5
    assert conformal_factor(np.arange(1.0, 10.0), 0.8) == 8.0  # n=9 -> k=8
    assert conformal_factor(np.array([0.1, 0.2, 0.3]), 0.8) is None  # too few: refuse to guess
    lo, hi = apply_factor(np.array([90.0]), np.array([100.0]), np.array([120.0]), 2.0)
    assert (lo[0], hi[0]) == (80.0, 140.0)


def test_calibration_widens_overconfident_band_out_of_sample():
    rng = np.random.default_rng(0)
    n, P, H = 400, 40, 7
    paths = np.zeros((n, P, H, 6))
    paths[..., 3] = 100 + rng.normal(0, 1.0, (n, P, H))  # model believes sd = 1
    actual = np.zeros((n, H, 6))
    actual[..., 3] = 100 + rng.normal(0, 3.0, (n, H))  # reality has sd = 3
    row = calibrate_split(paths, actual, (7,), 0.5, 0.8)[0]
    assert row["raw_coverage_test"] < 0.5  # overconfident before
    assert row["factor"] > 2.0
    assert 0.7 <= row["calibrated_coverage_test"] <= 0.9  # near the 0.8 target on unseen origins
    assert row["n_calibration"] == 200 and row["n_test"] == 200


def test_calibration_reports_insufficient_data():
    row = calibrate_split(np.ones((4, 5, 7, 6)), np.ones((4, 7, 6)), (7,), 0.5, 0.8)[0]
    assert row["factor"] is None and row["calibrated_coverage_test"] is None
    assert calibrate_split(np.ones((4, 1, 7, 6)), np.ones((4, 7, 6)), (7,)) == []


# ---------------------------------------------------------------- regime + rules
def test_regime_detection_and_no_lookahead():
    up = pd.Series(100 * 1.01 ** np.arange(200))
    down = pd.Series(100 * 0.99 ** np.arange(200))
    assert detect_regime(up).trend == "up" and detect_regime(down).trend == "down"
    calm_then_wild = pd.Series(100 * np.exp(np.cumsum(np.r_[np.tile([0.001, -0.001], 150), np.tile([0.08, -0.08], 20)])))
    assert detect_regime(calm_then_wild).volatility == "high"
    assert detect_regime(calm_then_wild.iloc[:300]).volatility != "high"
    with pytest.raises(DataValidationError):
        detect_regime(up.iloc[:20])


R = lambda trend="up", vol="normal", rv=0.8: Regime(trend, vol, rv, 0.5, 0.0)  # noqa: E731
P = SignalParams()


def test_decision_rules():
    assert decide(98, 105, 112, 100, R(), P).action == BUY
    assert decide(98, 101, 104, 100, R(), P).action == ABSTAIN  # edge too small
    assert decide(80, 105, 112, 100, R(), P).action == ABSTAIN  # downside too large
    assert decide(98, 105, 112, 100, R(trend="down"), P).action == ABSTAIN
    assert decide(98, 105, 112, 100, R(vol="high"), P).action == ABSTAIN
    d = decide(90, 96, 101, 100, R(vol="high"), P)
    assert d.action == SELL and d.target_fraction == 0.0  # exits are allowed even in high vol
    assert decide(98, 105, 112, 100, R(), P).target_fraction == pytest.approx(0.5)  # 0.40 / 0.80
    assert decide(98, 105, 112, 100, R(), P).reasons  # every decision is explained


def test_calibration_factor_changes_the_decision():
    assert decide(95, 105, 112, 100, R(), P).action == BUY  # raw r10 = -5%
    wide = SignalParams(interval_factor=2.5)  # calibrated r10 = -20%
    assert decide(95, 105, 112, 100, R(), wide).action == ABSTAIN


def test_position_size_is_never_leveraged():
    assert position_fraction(0.1, P) == 1.0
    assert position_fraction(0.1, SignalParams(max_fraction=5.0)) == 1.0
    assert position_fraction(0.0, P) == 0.0


# ---------------------------------------------------------------- execution
def test_rebalance_costs_and_limits():
    c = Costs(fee_bps=10, slippage_bps=5)
    buy = rebalance(10_000, 0, 100, 1.0, c)
    assert buy.price == pytest.approx(100.05) and buy.cash == pytest.approx(0.0, abs=1e-9) and buy.fee > 0
    assert buy.qty * 100 < 10_000  # costs were paid
    sell = rebalance(buy.cash, buy.qty, 100, 0.0, c)
    assert sell.qty == 0 and sell.price == pytest.approx(99.95) and sell.cash < 10_000
    assert rebalance(10_000, 0, 100, 5.0, c).qty == pytest.approx(buy.qty)  # clamped to 100%
    assert rebalance(10_000, 0, 100, -1.0, c).qty == 0  # no shorting
    assert rebalance(5_000, 50, 100, 0.501, c).qty_delta == 0  # below min trade size
    free = rebalance(10_000, 0, 100, 0.5, Costs(0, 0))
    assert free.cash == 5_000 and free.qty == 50


def test_performance_metrics():
    m = performance(np.array([100.0, 110.0, 99.0, 120.0]))
    assert m["total_return"] == pytest.approx(0.2) and m["max_drawdown"] == pytest.approx(-0.1)
    assert performance(np.array([100.0]))["sharpe"] is None
    flat = performance(np.full(10, 100.0))
    assert flat["total_return"] == 0 and flat["sharpe"] is None


# ---------------------------------------------------------------- backtest
class ScriptedForecaster:
    """Forecasts a fixed return, so the rule fires deterministically."""

    name, device = "scripted", "cpu"

    def __init__(self, ret: float) -> None:
        self.ret, self.seen = ret, []

    def sample_paths(self, context, future_ts, n_paths, seed):
        self.seen.append(pd.Timestamp(context["timestamp"].iloc[-1]))
        end = float(context["close"].iloc[-1]) * (1 + self.ret)
        close = np.linspace(end * 0.99, end * 1.01, n_paths)[:, None] * np.ones((1, len(future_ts)))
        return np.repeat(close[:, :, None], len(FEATURE_COLUMNS), axis=2)


LOOSE = SignalParams(abstain_in_high_vol=False, block_buy_in_downtrend=False)
CFG = BacktestConfig(lookback=100, n_paths=5, rebalance_every=7, n_decisions=10, costs=Costs(10, 5))


def test_backtest_executes_next_open_and_charges_costs(ohlcv):
    res = run_backtest(ohlcv, ScriptedForecaster(+0.05), LOOSE, CFG)
    assert len(res.decisions) == 10 and all(d["action"] == BUY for d in res.decisions)
    first_decision = pd.Timestamp(res.decisions[0]["timestamp"])
    first_trade = pd.Timestamp(res.trades[0]["timestamp"])
    assert first_trade == first_decision + pd.Timedelta(days=1)  # filled on the NEXT bar
    row = ohlcv[ohlcv["timestamp"] == first_trade].iloc[0]
    assert res.trades[0]["price"] == pytest.approx(row["open"] * 1.0005)  # at the open, plus slippage
    assert res.metrics["strategy"]["fees_paid"] > 0 and res.metrics["strategy"]["n_trades"] >= 1
    assert res.equity["timestamp"].iloc[0] == first_trade and len(res.equity) == CFG.rebalance_every * 9 + 1


def test_always_sell_stays_in_cash_and_zero_cost_full_long_equals_buy_hold(ohlcv):
    flat = run_backtest(ohlcv, ScriptedForecaster(-0.05), LOOSE, CFG)
    assert flat.trades == [] and (flat.equity["equity"] == CFG.initial_cash).all()
    free = BacktestConfig(lookback=100, n_paths=5, rebalance_every=7, n_decisions=10, costs=Costs(0, 0, 1.0))
    full = SignalParams(abstain_in_high_vol=False, block_buy_in_downtrend=False, target_annual_vol=100.0)
    res = run_backtest(ohlcv, ScriptedForecaster(+0.05), full, free)
    np.testing.assert_allclose(res.equity["equity"], res.equity["buy_hold"])  # accounting identity


def test_backtest_has_no_lookahead(ohlcv):
    """Changing the future must not change any earlier decision."""
    cfg = BacktestConfig(lookback=100, n_paths=10, rebalance_every=7, n_decisions=12)
    base = run_backtest(ohlcv, FakeForecaster(), LOOSE, cfg)
    cut = pd.Timestamp(base.decisions[5]["timestamp"])
    tampered = ohlcv.copy()
    later = tampered["timestamp"] > cut
    tampered.loc[later, ["open", "high", "low", "close"]] *= 3.0
    other = run_backtest(tampered, FakeForecaster(), LOOSE, cfg)
    assert base.decisions[:6] == other.decisions[:6]
    fc = ScriptedForecaster(0.05)
    run_backtest(ohlcv, fc, LOOSE, CFG)
    decision_ts = [pd.Timestamp(d["timestamp"]) for d in run_backtest(ohlcv, ScriptedForecaster(0.05), LOOSE, CFG).decisions]
    assert fc.seen == decision_ts  # the model's newest bar is always the decision bar


def test_backtest_survives_forecast_failures_and_short_data(ohlcv):
    class Broken(FakeForecaster):
        def sample_paths(self, *a, **k):
            raise ForecastError("out of memory")

    res = run_backtest(ohlcv, Broken(), LOOSE, CFG)
    assert len(res.errors) == 10 and res.decisions == [] and res.trades == []
    assert res.metrics["strategy"]["total_return"] == 0.0
    with pytest.raises(DataValidationError):
        run_backtest(ohlcv.iloc[:40], FakeForecaster(), LOOSE, CFG)


def test_decide_at_uses_only_rows_up_to_t(ohlcv):
    a = decide_at(ohlcv, 300, FakeForecaster(), P, 100, 10)
    b = decide_at(ohlcv.iloc[:301], 300, FakeForecaster(), P, 100, 10)
    assert a.decision == b.decision and a.decision_ts == ohlcv["timestamp"].iloc[300]


# ---------------------------------------------------------------- paper simulator
@pytest.fixture
def conn():
    return connect(":memory:")


def test_paper_cycle_is_idempotent_and_fills_at_next_open(conn, ohlcv):
    with pytest.raises(simulator.PaperError):
        simulator.step(conn, "X", ohlcv, ScriptedForecaster(0.05), LOOSE, 100, 5)  # no account yet
    simulator.init_account(conn, 10_000)
    with pytest.raises(simulator.PaperError):
        simulator.init_account(conn, 10_000)  # never reset implicitly
    day1 = ohlcv.iloc[:400]
    out = simulator.step(conn, "X", day1, ScriptedForecaster(0.05), LOOSE, 100, 5)
    assert out["decision"]["action"] == BUY and out["decision"]["status"] == "PENDING" and out["fills"] == []
    again = simulator.step(conn, "X", day1, ScriptedForecaster(0.05), LOOSE, 100, 5)
    assert again["decision"] is None and "already recorded" in again["note"]
    assert simulator.account_status(conn, {"X": 1.0})["cash"] == 10_000  # nothing filled without a new candle

    day2 = ohlcv.iloc[:401]
    out2 = simulator.step(conn, "X", day2, ScriptedForecaster(-0.05), LOOSE, 100, 5)
    fill = out2["fills"][0]
    assert fill["status"] == "FILLED" and fill["price"] == pytest.approx(ohlcv["open"].iloc[400] * 1.0005)
    assert fill["fill_ts"] == str(ohlcv["timestamp"].iloc[400]) and out2["decision"]["action"] == SELL
    st = simulator.account_status(conn, {"X": float(ohlcv["close"].iloc[400])})
    assert st["positions"][0]["qty"] > 0 and st["simulated"] is True

    out3 = simulator.step(conn, "X", ohlcv.iloc[:402], ScriptedForecaster(0.0), LOOSE, 100, 5)
    assert out3["fills"][0]["qty_after"] == 0 and out3["decision"]["status"] == "ABSTAIN"
    assert simulator.account_status(conn, {})["positions"] == []
    events = list(simulator.audit_frame(conn)["event"])
    assert events.count("paper_decision") == 3 and events.count("paper_fill") == 2 and "paper_init" in events
    assert len(simulator.orders_frame(conn)) == 3


def test_paper_records_failed_decisions(conn, ohlcv):
    class Broken(FakeForecaster):
        def sample_paths(self, *a, **k):
            raise ForecastError("model crashed")

    simulator.init_account(conn)
    out = simulator.step(conn, "X", ohlcv, Broken(), LOOSE, 100, 5)
    assert "model crashed" in out["error"] and simulator.orders_frame(conn).empty
    assert "paper_decision_failed" in list(simulator.audit_frame(conn)["event"])


def test_project_contains_no_trading_connectivity():
    """Safety rule: no exchange client library, no order endpoint, no credential handling in the code."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    banned = ["ccxt", "python-binance", "binance.client", "/api/v3/order", "/api/v3/account", "api_secret",
              "apikey", "x-mbx-apikey", "create_order", "websocket"]
    for path in [*root.glob("app/**/*.py"), *root.glob("scripts/*.py"), *root.glob("requirements*.txt")]:
        text = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in text, f"{word!r} found in {path}"
