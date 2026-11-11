"""Regression tests for defects found in the code review (each test failed before its fix)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import services
from app.backtest.engine import BacktestConfig
from app.backtest.execution import Costs, rebalance
from app.core import config
from app.core.errors import ConfigError, ForecastError
from app.core.runs import dumps, safe_console, write_json_new
from app.data import engine
from app.evaluation.calibration import calibrate_split
from app.evaluation.rolling import EvalConfig
from app.forecast.service import make_forecast
from app.paper import simulator
from app.signals.regime import Regime, RegimeParams, detect_regime
from app.signals.rules import BUY, SignalParams, decide
from app.storage.db import connect
from tests.conftest import FakeForecaster

ROOT = Path(__file__).resolve().parents[1]
S = config.SYNTHETIC_SYMBOL


def test_rebalance_never_leaves_negative_cash_or_quantity():
    """Float rounding used to leave cash at about -1e-11 after a full buy."""
    rng = np.random.default_rng(0)
    for _ in range(20_000):
        cash, qty = float(rng.uniform(0, 1e5)), float(rng.uniform(0, 50)) * (rng.random() < 0.7)
        price, target = float(10 ** rng.uniform(-3, 5)), float(rng.uniform(-0.2, 1.3))
        costs = Costs(float(rng.uniform(0, 100)), float(rng.uniform(0, 100)), 0.0)
        fill = rebalance(cash, qty, price, target, costs)
        assert fill.cash >= 0.0 and fill.qty >= 0.0
        before, after = cash + qty * price, fill.cash + fill.qty * price
        assert after <= before * (1 + 1e-9) + 1e-9  # trading can only cost money, never create it


def test_buy_with_zero_measured_volatility_is_not_turned_into_an_exit():
    d = decide(99, 105, 110, 100, Regime("up", "normal", 0.0, 0.5, 0.0), SignalParams())
    assert d.action == BUY and d.target_fraction == 1.0


def test_flat_market_is_sideways_not_down():
    assert detect_regime(pd.Series(np.full(200, 100.0))).trend == "sideways"


def test_decide_rejects_unusable_numbers():
    r = Regime("up", "normal", 0.5, 0.5, 0.0)
    with pytest.raises(ForecastError):
        decide(1, 2, 3, 0.0, r, SignalParams())
    with pytest.raises(ForecastError):
        decide(1, float("nan"), 3, 100.0, r, SignalParams())


def test_empty_calibration_input_returns_nothing_without_nan():
    assert calibrate_split(np.empty((0, 5, 7, 6)), np.empty((0, 7, 6)), (7,)) == []


@pytest.mark.parametrize("make", [
    lambda: calibrate_split(np.ones((4, 5, 7, 6)), np.ones((4, 7, 6)), (7,), level=1.0),  # was ZeroDivisionError
    lambda: calibrate_split(np.ones((4, 5, 7, 6)), np.ones((4, 7, 6)), (7,), calib_fraction=0.0),
    lambda: BacktestConfig(rebalance_every=0),  # used to run silently
    lambda: BacktestConfig(n_decisions=0),
    lambda: BacktestConfig(n_paths=1),
    lambda: BacktestConfig(initial_cash=-1.0),
    lambda: BacktestConfig(initial_cash=float("nan")),
    lambda: Costs(fee_bps=-5.0),
    lambda: Costs(slippage_bps=float("inf")),
    lambda: SignalParams(horizon=0),
    lambda: SignalParams(min_edge=-0.1),
    lambda: SignalParams(interval_factor=0.0),
    lambda: EvalConfig(horizons=(0,)),
    lambda: EvalConfig(n_origins=0),
    lambda: RegimeParams(low_pct=0.9, high_pct=0.1),
])
def test_out_of_range_settings_are_rejected(make):
    with pytest.raises(ConfigError):
        make()


def test_single_path_forecast_is_a_controlled_error(ohlcv):
    with pytest.raises(ForecastError, match="at least 2"):  # was an uncaught ValueError
        make_forecast(ohlcv, FakeForecaster(), 100, 7, 1)


def test_unfinished_candle_is_never_stored_even_without_explicit_now():
    conn = connect(":memory:")
    today = pd.Timestamp.now(tz="UTC").floor("D")
    out = engine.store_candles(conn, "X", engine.synthetic_candles(100, end=str(today.date())), "csv")
    assert out["incomplete_dropped"] == 1 and out["inserted"] == 99
    assert engine.last_timestamp(conn, "X") == today - pd.Timedelta(days=1)


def test_json_output_is_strict(tmp_path):
    """numpy ints used to be written as strings and NaN as the non-JSON token NaN."""
    payload = {"i": np.int64(3), "f": np.float64(1.5), "nan": float("nan"), "inf": np.inf,
               "arr": np.array([1.0, np.nan]), "ts": pd.Timestamp("2024-01-01"), 5: "int key"}
    path = write_json_new(tmp_path / "x.json", payload)
    back = json.loads(path.read_text(), parse_constant=lambda c: pytest.fail(f"non-JSON constant {c}"))
    assert back == {"i": 3, "f": 1.5, "nan": None, "inf": None, "arr": [1.0, None],
                    "ts": "2024-01-01 00:00:00", "5": "int key"}


def test_paper_account_rejects_nan_cash():
    with pytest.raises(simulator.PaperError):  # was sqlite3.IntegrityError
        simulator.init_account(connect(":memory:"), float("nan"))


# ----------------------------------------------------------------- CLI level
@pytest.fixture
def kql(tmp_path, monkeypatch):
    for name, value in [("ARTIFACTS_DIR", tmp_path), ("REPORTS_DIR", tmp_path / "reports"),
                        ("DB_PATH", tmp_path / "kql.sqlite3"), ("FORECAST_CACHE_DIR", tmp_path / "cache"),
                        ("MODELS_DIR", tmp_path / "models")]:
        monkeypatch.setattr(config, name, value)
    spec = importlib.util.spec_from_file_location("kql_cli", ROOT / "scripts" / "kql.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calibration_fitted_inside_the_backtest_period_is_not_used(kql):
    """A factor fitted on bars the backtest trades through would leak the future."""
    assert kql.main(["data", "demo", "--rows", "900"]) == 0
    assert kql.main(["calibrate", "--symbol", S, "--n-origins", "12", "--lookback", "200"]) == 0
    run = services.calibration_runs()[0]
    row = next(r for r in run["calibration"] if r["horizon"] == 7)
    fit_end = pd.Timestamp(row["fit_end_timestamp"])
    assert row["factor"] is not None

    short = BacktestConfig(lookback=200, n_decisions=8)  # 8 weeks: starts after the fit window
    long = BacktestConfig(lookback=200, n_decisions=60)  # 60 weeks: overlaps the fit window
    conn = services.open_db()
    start_short, start_long = services.backtest_start(conn, S, short), services.backtest_start(conn, S, long)
    assert start_long <= fit_end < start_short
    used, why_used = services.signal_params(S, "baseline-bootstrap", start_short)
    refused, why_refused = services.signal_params(S, "baseline-bootstrap", start_long)
    assert used.interval_factor == pytest.approx(row["factor"]) and "calibration run" in why_used
    assert refused.interval_factor == 1.0 and "leak" in why_refused
    # live-style use (paper step) has no "before": any realised calibration is fine
    assert services.signal_params(S, "baseline-bootstrap")[0].interval_factor == pytest.approx(row["factor"])

    assert kql.main(["backtest", "--symbol", S, "--lookback", "200", "--n-decisions", "60"]) == 0
    summary = services.backtest_runs()[0]
    assert "leak" in summary["interval_factor_source"] and summary["config"]["signal"]["interval_factor"] == 1.0


@pytest.mark.parametrize("argv", [
    ["forecast", "--symbol", S, "--n-paths", "1"],
    ["forecast", "--symbol", S, "--n-paths", "0"],
    ["forecast", "--symbol", S, "--horizon", "0"],
    ["calibrate", "--symbol", S, "--n-origins", "0"],
    ["backtest", "--symbol", S, "--rebalance-every", "0"],
    ["backtest", "--symbol", S, "--n-decisions", "-3"],
    ["backtest", "--symbol", S, "--horizon", "0"],
])
def test_cli_rejects_bad_numbers_at_parse_time(kql, argv, capsys):
    with pytest.raises(SystemExit) as exc:
        kql.main(argv)
    assert exc.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["calibrate", "--symbol", S, "--level", "1.0"],
    ["calibrate", "--symbol", S, "--calib-fraction", "0"],
    ["backtest", "--symbol", S, "--fee-bps", "-5"],
    ["backtest", "--symbol", S, "--cash", "-1"],
    ["paper", "init", "--cash", "nan"],
    ["data", "import", "--symbol", "X", "--csv", "/nonexistent/file.csv"],  # was FileNotFoundError traceback
])
def test_cli_bad_values_exit_cleanly(kql, argv):
    assert kql.main(["data", "demo"]) == 0
    assert kql.main(argv) == 2


def test_cli_reports_malformed_csv_cleanly(kql, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    assert kql.main(["data", "import", "--symbol", "X", "--csv", str(empty)]) == 2


def test_backtest_with_failing_model_is_flagged(kql, monkeypatch, capsys):
    class Broken(FakeForecaster):
        def sample_paths(self, *a, **k):
            raise ForecastError("out of memory")

    assert kql.main(["data", "demo"]) == 0
    monkeypatch.setattr(services, "get_forecaster", lambda *a, **k: Broken())
    assert kql.main(["backtest", "--symbol", S, "--n-decisions", "4"]) == 1  # used to return 0
    assert "4 of 4 decisions failed" in capsys.readouterr().out


def test_p0_cli_missing_data_file_exits_cleanly(p0):
    assert p0.main(["evaluate", "--data", "/nonexistent/file.csv"]) == 2


def test_console_that_cannot_encode_a_path_does_not_crash(monkeypatch):
    """Windows cp1252 console + non-ASCII user folder used to raise UnicodeEncodeError."""
    import io
    import sys

    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    with pytest.raises(UnicodeEncodeError):
        print("C:\\Users\\کاربر\\artifacts")
    safe_console()
    print("C:\\Users\\کاربر\\artifacts")
    print(dumps({"path": "C:\\Users\\کاربر"}))
    sys.stdout.flush()
    assert b"\\u06a9" in raw.getvalue()


def test_corrupt_or_foreign_cache_entry_is_recomputed(tmp_path, ohlcv):
    from app.forecast.base import make_window
    from app.forecast.registry import CachedForecaster

    cached = CachedForecaster(FakeForecaster(), tmp_path)
    win = make_window(ohlcv, 300, 100, 7)
    good = cached.sample_paths(win.context, win.future_ts, 4, 9)
    entry = next((tmp_path / "fake").glob("*.npy"))
    entry.write_bytes(b"not a numpy file")  # e.g. the PC lost power while writing
    again = cached.sample_paths(win.context, win.future_ts, 4, 9)
    np.testing.assert_array_equal(good, again)
    np.save(entry, np.zeros((2, 2)))  # wrong shape
    np.testing.assert_array_equal(cached.sample_paths(win.context, win.future_ts, 4, 9), good)
    assert cached.hits == 0 and cached.misses == 3


def test_binance_malformed_or_out_of_range_pages_are_controlled():
    from app.core.errors import DataValidationError
    from app.data.binance import PAGE_LIMIT, fetch_klines
    from tests.test_data import kline

    with pytest.raises(DataValidationError, match="malformed"):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=lambda u: [["not-a-number"]])
    with pytest.raises(DataValidationError, match="malformed"):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=lambda u: [[]])
    same_page = [kline(i) for i in range(PAGE_LIMIT)]  # a server that ignores startTime
    with pytest.raises(DataValidationError, match="outside the requested range"):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=lambda u: same_page)


def test_paper_step_warns_about_stale_data(kql):
    conn = services.open_db()
    engine.store_candles(conn, "OLD", engine.synthetic_candles(300, end="2024-01-31"), "test")
    simulator.init_account(conn)
    out = services.paper_step(conn, "OLD", "baseline-bootstrap")
    assert "days old" in out["warning"]
    engine.store_candles(conn, S, engine.synthetic_candles(300), "synthetic")
    assert "warning" not in services.paper_step(conn, S, "baseline-bootstrap")


def test_backtest_fills_at_the_gapped_open_not_at_the_decision_close(ohlcv):
    """The shared fixture has open == previous close, so it could not tell these two apart."""
    from app.backtest.engine import run_backtest
    from tests.test_research import CFG, LOOSE, ScriptedForecaster

    gapped = ohlcv.copy()
    gapped["open"] = gapped["open"] * 1.03  # every bar opens 3% above the previous close
    gapped["high"] = gapped[["open", "high"]].max(axis=1)
    res = run_backtest(gapped, ScriptedForecaster(+0.05), LOOSE, CFG)
    trade = res.trades[0]
    i = gapped.index[gapped["timestamp"] == pd.Timestamp(trade["timestamp"])][0]
    assert trade["price"] == pytest.approx(gapped["open"].iloc[i] * 1.0005)
    assert trade["price"] > gapped["close"].iloc[i - 1] * 1.02  # the gap is paid, not skipped
