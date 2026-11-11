from __future__ import annotations

import datetime as dt
import sqlite3

import numpy as np
import pandas as pd
import pytest

from app.core.errors import DataValidationError
from app.data import engine
from app.forecast.baselines import BootstrapForecaster
from app.forecast.base import check_paths, make_window
from app.forecast.registry import CachedForecaster, build_forecaster, model_available
from app.forecast.service import load_forecast_quantiles, load_forecast_runs, make_forecast, save_forecast
from app.storage.db import audit, connect
from tests.conftest import FakeForecaster


@pytest.fixture
def conn():
    return connect(":memory:")


class StubProvider:
    name = "stub"

    def __init__(self, df):
        self.df, self.calls = df, []

    def fetch(self, symbol, start_ms):
        self.calls.append(start_ms)
        return self.df[self.df["timestamp"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]


def test_store_and_load_roundtrip(conn, ohlcv):
    out = engine.store_candles(conn, "X", ohlcv, "test")
    assert out["inserted"] == len(ohlcv)
    back = engine.load_candles(conn, "X")
    pd.testing.assert_frame_equal(back, ohlcv, check_exact=False)
    assert engine.data_status(conn)[0]["missing_bars"] == 0


def test_incremental_update_only_adds_new_complete_candles(conn, ohlcv):
    provider = StubProvider(ohlcv)
    now = (ohlcv["timestamp"].iloc[299] + pd.Timedelta(hours=3)).to_pydatetime()  # candle 299 still open
    first = engine.update_symbol(conn, StubProvider(ohlcv.iloc[:300]), "X", now=now)
    assert first["inserted"] == 299 and first["incomplete_dropped"] == 1
    second = engine.update_symbol(conn, provider, "X", now=dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
    assert second["inserted"] == len(ohlcv) - 299 and second["conflicting_values"] == 0
    assert provider.calls[0] == int(ohlcv["timestamp"].iloc[298].timestamp() * 1000)  # resumes at last stored bar
    third = engine.update_symbol(conn, provider, "X", now=dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
    assert third["inserted"] == 0 and len(engine.load_candles(conn, "X")) == len(ohlcv)


def test_stored_candles_are_never_rewritten(conn, ohlcv):
    engine.store_candles(conn, "X", ohlcv.iloc[:100], "test")
    changed = ohlcv.iloc[90:120].copy()
    changed.loc[changed.index[0], ["close", "high"]] = changed["high"].iloc[0] * 2  # provider "revised" history
    out = engine.store_candles(conn, "X", changed, "test")
    assert out["conflicting_values"] == 2 and out["inserted"] == 20
    assert engine.load_candles(conn, "X")["close"].iloc[90] == pytest.approx(ohlcv["close"].iloc[90])


def test_invalid_or_gapped_updates_store_nothing(conn, ohlcv):
    engine.store_candles(conn, "X", ohlcv.iloc[:100], "test")
    with pytest.raises(DataValidationError, match="gap"):
        engine.store_candles(conn, "X", ohlcv.iloc[105:120], "test")
    bad = ohlcv.iloc[100:120].copy()
    bad.loc[bad.index[3], "close"] = np.nan
    with pytest.raises(DataValidationError):
        engine.store_candles(conn, "X", bad, "test")
    assert len(engine.load_candles(conn, "X")) == 100
    with pytest.raises(DataValidationError):
        engine.load_candles(conn, "UNKNOWN")


def test_audit_log_is_append_only(conn):
    with conn:
        audit(conn, "x", {"a": 1})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit_log SET event = 'y'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM audit_log")


def test_bootstrap_baseline_contract(ohlcv):
    win = make_window(ohlcv, 300, 100, 14)
    fc = BootstrapForecaster()
    a, b = fc.sample_paths(win.context, win.future_ts, 50, 1), fc.sample_paths(win.context, win.future_ts, 50, 1)
    check_paths(a, 50, 14)
    np.testing.assert_array_equal(a, b)
    assert (a[..., 1] >= a[..., 3]).all() and (a[..., 2] <= a[..., 3]).all() and (a > 0).all()
    rets = np.abs(np.diff(np.log(win.context["close"])))
    assert np.abs(np.log(a[:, 0, 3] / win.context["close"].iloc[-1])).max() <= rets.max() + 1e-12  # only seen returns


def test_registry(monkeypatch, tmp_path):
    from app.core import config
    from app.core.errors import ModelUnavailableError

    assert model_available("baseline-bootstrap")[0]
    monkeypatch.setattr(config, "KRONOS_SRC_DIR", tmp_path)
    assert not model_available("kronos-small")[0] and not model_available("nope")[0]
    assert build_forecaster("baseline-bootstrap").name == "baseline-bootstrap"
    with pytest.raises(ModelUnavailableError):
        build_forecaster("nope")


def test_forecast_cache_hits_and_invalidates_on_changed_context(tmp_path, ohlcv):
    inner = FakeForecaster()
    cached = CachedForecaster(inner, tmp_path)
    win = make_window(ohlcv, 300, 100, 7)
    a = cached.sample_paths(win.context, win.future_ts, 4, 9)
    b = cached.sample_paths(win.context, win.future_ts, 4, 9)
    np.testing.assert_array_equal(a, b)
    assert (cached.hits, cached.misses, len(inner.calls)) == (1, 1, 1)
    changed = win.context.copy()
    changed.loc[5, "close"] *= 1.0001
    cached.sample_paths(changed, win.future_ts, 4, 9)
    cached.sample_paths(win.context, win.future_ts, 4, 10)
    assert cached.misses == 3


def test_forecast_service_persists_quantiles(conn, ohlcv):
    fc = make_forecast(ohlcv, FakeForecaster(), lookback=100, horizon=7, n_paths=30)
    assert fc.origin_ts == ohlcv["timestamp"].iloc[-1] and fc.horizon == 7
    assert (fc.p10 <= fc.p50).all() and (fc.p50 <= fc.p90).all()
    assert fc.future_ts.iloc[0] == (ohlcv["timestamp"].iloc[-1] + pd.Timedelta(days=1)).tz_localize(None)
    run_id = save_forecast(conn, "X", fc)
    q = load_forecast_quantiles(conn, run_id)
    np.testing.assert_allclose(q["p50"], fc.p50)
    assert load_forecast_runs(conn, "X")["model"].iloc[0] == "fake"
    same = make_forecast(ohlcv, FakeForecaster(), 100, 7, 30)
    np.testing.assert_array_equal(same.paths, fc.paths)  # per-date seed is deterministic
