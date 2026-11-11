"""Timeframes, endpoint failover, sampling/window settings and interval-aware data storage."""
from __future__ import annotations

import datetime as dt
import sqlite3
import urllib.error

import numpy as np
import pandas as pd
import pytest

from app.core import config, timeframes
from app.core.errors import ConfigError, DataValidationError
from app.data import binance, engine
from app.forecast.base import make_window
from app.forecast.registry import CachedForecaster
from app.forecast.service import load_forecast_runs, make_forecast, save_forecast
from app.storage.db import connect
from tests.conftest import FakeForecaster
from tests.test_data import kline


@pytest.fixture(autouse=True)
def _forget_host():
    binance.reset_active_base_url()
    yield
    binance.reset_active_base_url()


# ------------------------------------------------------------------ timeframes
def test_timeframes_map_interval_to_step_and_year_length():
    assert timeframes.normalize("1D") == "1d"
    assert timeframes.get("4h").step == pd.Timedelta(hours=4)
    assert timeframes.bars_per_year("1h") == 8760 and timeframes.bars_per_year("1d") == 365
    assert timeframes.freq("1d") == "1D"
    assert timeframes.bars_between("2024-01-01", "2024-01-03", "1d") == 3
    with pytest.raises(ConfigError, match="unsupported interval"):
        timeframes.normalize("5m")


def test_infer_interval_uses_the_smallest_step():
    hourly = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    assert timeframes.infer_interval(hourly) == "1h"
    daily = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    assert timeframes.infer_interval(daily) == "1d"
    # a missing bar must look like a gap, not like a coarser interval
    gapped = daily.delete([4])
    assert timeframes.infer_interval(gapped) == "1d"
    assert timeframes.infer_interval([daily[0]]) is None


# ------------------------------------------------------------------ config
def test_model_specs_match_the_documented_hugging_face_ids():
    small, base = config.MODELS["small"], config.MODELS["base"]
    assert small.repo_id == "NeoQuasar/Kronos-small"
    assert base.repo_id == "NeoQuasar/Kronos-base"
    assert small.tokenizer_id == base.tokenizer_id == "NeoQuasar/Kronos-Tokenizer-base"
    assert small.parameters == "24.7M" and base.parameters == "102.3M"
    assert small.context_length == base.context_length == config.MAX_CONTEXT == 512
    assert config.model_spec("kronos-small") is small
    with pytest.raises(ValueError):
        config.model_spec("kronos-huge")


def test_binance_hosts_are_primary_then_fallback():
    assert config.BINANCE_BASE_URLS[0] == config.BINANCE_PRIMARY_URL
    assert config.BINANCE_BASE_URL == config.BINANCE_BASE_URLS[0]
    assert "https://api.binance.com" in config.BINANCE_BASE_URLS
    settings = config.effective_settings()
    assert settings["binance_primary_url"] == config.BINANCE_PRIMARY_URL
    assert settings["models"]["small"]["model_id"] == "NeoQuasar/Kronos-small"
    assert settings["max_context"] == 512 and settings["max_horizon"] == 96


def test_window_limits_are_enforced():
    from tests.conftest import make_ohlcv

    df = make_ohlcv(600)
    with pytest.raises(DataValidationError, match="exceeds the model maximum"):
        make_window(df, 590, config.MAX_CONTEXT + 1, 5)
    with pytest.raises(DataValidationError, match="MAX_HORIZON"):
        make_window(df, 590, 100, config.MAX_HORIZON + 1)


def test_window_infers_intraday_step_and_builds_hourly_targets():
    df = engine.synthetic_candles(300, interval="1h", seed=3)
    win = make_window(df, len(df), 200, 6)
    assert (win.future_ts.diff().dropna() == pd.Timedelta(hours=1)).all()
    assert win.future_ts.iloc[0] == win.context["timestamp"].iloc[-1].tz_localize(None) + pd.Timedelta(hours=1)


# ------------------------------------------------------------------ sampling
def test_sampling_config_rejects_out_of_range_values():
    assert config.SamplingConfig().as_plain() == {"temperature": 1.0, "top_k": 0, "top_p": 0.9}
    for kwargs in ({"temperature": 0}, {"temperature": float("nan")}, {"top_p": 0}, {"top_p": 1.5},
                   {"top_k": -1}, {"top_k": 1.5}):
        with pytest.raises(ConfigError):
            config.SamplingConfig(**kwargs)


def test_forecast_cache_key_depends_on_the_sampling_settings(tmp_path):
    from tests.conftest import make_ohlcv

    df = make_ohlcv(600)
    win = make_window(df, 550, 100, 5)
    cache_dir = tmp_path / "cache"

    class WithSampling(FakeForecaster):
        def __init__(self, temperature: float) -> None:
            super().__init__()
            self.sampling = config.SamplingConfig(temperature=temperature)

    first = CachedForecaster(WithSampling(1.0), cache_dir)
    a = first.sample_paths(win.context, win.future_ts, 4, 7)
    first.sample_paths(win.context, win.future_ts, 4, 7)
    assert first.hits == 1 and first.misses == 1

    other = CachedForecaster(WithSampling(1.5), cache_dir)
    b = other.sample_paths(win.context, win.future_ts, 4, 7)
    assert other.hits == 0 and other.misses == 1  # a different temperature is a different key
    assert a.shape == b.shape


# ------------------------------------------------------------------ Binance failover
def test_geo_block_switches_to_the_fallback_host_and_remembers_it():
    hosts = ["https://data-api.binance.vision", "https://api.binance.com"]
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        if "data-api.binance.vision" in url:
            raise urllib.error.HTTPError(url, 451, "Unavailable For Legal Reasons", None, None)
        return [kline(0), kline(1)]

    rows = binance.fetch_klines("BTCUSDT", "1d", hosts, fetcher=fetcher)
    assert len(rows) == 2 and binance.active_base_url() == "https://api.binance.com"
    assert calls[0].startswith("https://data-api.binance.vision") and calls[1].startswith("https://api.binance.com")

    calls.clear()
    binance.fetch_klines("BTCUSDT", "1d", hosts, fetcher=fetcher)  # straight to the working host now
    assert len(calls) == 1 and calls[0].startswith("https://api.binance.com")


def test_403_is_treated_as_a_geo_block_but_other_errors_are_not_retried():
    hosts = ["https://a.invalid", "https://b.invalid"]
    calls: list[str] = []

    def forbidden(url: str):
        calls.append(url)
        if url.startswith("https://a.invalid"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        return [kline(0)]

    assert len(binance.fetch_klines("X", "1d", hosts, fetcher=forbidden)) == 1
    assert calls[0].startswith("https://a.invalid") and calls[1].startswith("https://b.invalid")

    binance.reset_active_base_url()
    calls.clear()

    def server_error(url: str):
        calls.append(url)
        raise urllib.error.HTTPError(url, 500, "boom", None, None)

    with pytest.raises(DataValidationError, match="HTTP 500"):
        binance.fetch_klines("X", "1d", hosts, fetcher=server_error)
    assert len(calls) == 1  # a server error on one host is not silently retried on the other


def test_all_hosts_blocked_is_one_clear_error():
    def blocked(url: str):
        raise urllib.error.HTTPError(url, 451, "blocked", None, None)

    with pytest.raises(DataValidationError, match="no Binance market-data host answered"):
        binance.fetch_klines("X", "1d", ["https://a.invalid", "https://b.invalid"], fetcher=blocked)


def test_geo_block_error_names_the_host_and_status():
    def blocked(url: str):
        raise urllib.error.HTTPError(url, 451, "blocked", None, None)

    with pytest.raises(DataValidationError, match=r"https://a.invalid: HTTP 451"):
        binance.fetch_klines("X", "1d", "https://a.invalid", fetcher=blocked)


def test_endpoint_candidates_are_ordered_and_deduplicated():
    assert binance.endpoint_candidates(["https://a/", "https://a", "https://b"]) == ["https://a", "https://b"]
    assert binance.endpoint_candidates("https://only.invalid") == ["https://only.invalid"]
    with pytest.raises(DataValidationError):
        binance.endpoint_candidates(["  "])


def test_provider_remembers_the_host_and_stores_the_requested_interval():
    conn = connect(":memory:")
    def fetcher(url: str):
        if "vision" in url:
            raise urllib.error.HTTPError(url, 451, "blocked", None, None)
        return [kline(0), kline(1)]
    provider = engine.BinanceProvider(base_urls=["https://data-api.binance.vision", "https://api.binance.com"],
                                      interval="1d", fetcher=fetcher)
    out = engine.update_symbol(conn, provider, "BTCUSDT", now=dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
    assert out["inserted"] == 2 and out["interval"] == "1d"
    assert provider.last_base_url == "https://api.binance.com"


# ------------------------------------------------------------------ interval-aware storage
def test_hourly_candles_roundtrip_and_gap_detection():
    conn = connect(":memory:")
    hourly = engine.synthetic_candles(100, interval="1h", seed=5, end="2024-03-01")
    out = engine.store_candles(conn, "H", hourly, "test", interval="1h")
    assert out["inserted"] == 100 and out["interval"] == "1h"
    back = engine.load_candles(conn, "H", "1h")
    pd.testing.assert_frame_equal(back, hourly, check_exact=False)
    assert engine.data_status(conn, "1h")[0]["missing_bars"] == 0
    assert engine.data_status(conn, "1d") == []

    with_gap = hourly.copy()
    with_gap["timestamp"] = with_gap["timestamp"] + pd.to_timedelta(np.where(with_gap.index >= 50, 2, 0), unit="h")
    with pytest.raises(DataValidationError, match="gap"):
        engine.store_candles(conn, "H", with_gap, "test", interval="1h")


def test_hourly_incomplete_candle_is_dropped_using_the_hour_step():
    conn = connect(":memory:")
    hourly = engine.synthetic_candles(20, interval="1h", seed=6, end="2024-03-01 12:00")
    last = hourly["timestamp"].iloc[-1].to_pydatetime()
    out = engine.store_candles(conn, "H", hourly, "test", now=last + dt.timedelta(minutes=30), interval="1h")
    assert out["incomplete_dropped"] == 1 and out["inserted"] == 19
    out2 = engine.store_candles(conn, "H", hourly, "test", now=last + dt.timedelta(hours=1), interval="1h")
    assert out2["inserted"] == 1


def test_daily_and_hourly_series_of_the_same_symbol_do_not_mix():
    conn = connect(":memory:")
    engine.store_candles(conn, "X", engine.synthetic_candles(50, seed=1, end="2024-02-01"), "test", interval="1d")
    engine.store_candles(conn, "X", engine.synthetic_candles(50, seed=2, end="2024-02-01", interval="1h"), "test",
                         interval="1h")
    assert len(engine.load_candles(conn, "X", "1d")) == 50
    assert len(engine.load_candles(conn, "X", "1h")) == 50
    with pytest.raises(DataValidationError, match="no 4h candles"):
        engine.load_candles(conn, "X", "4h")


# ------------------------------------------------------------------ forecast storage
def test_forecast_runs_are_separated_by_interval_and_migrate_old_databases(tmp_path):
    legacy_path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(legacy_path)
    legacy.executescript(
        "CREATE TABLE forecast_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL, "
        "symbol TEXT NOT NULL, model TEXT NOT NULL, origin_ts TEXT NOT NULL, last_close REAL NOT NULL, "
        "horizon INTEGER NOT NULL, n_paths INTEGER NOT NULL, seed INTEGER NOT NULL, lookback INTEGER NOT NULL);"
    )
    legacy.commit()
    legacy.close()
    conn = connect(legacy_path)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(forecast_runs)")}
    assert "interval" in columns  # an existing database is migrated additively

    df = engine.synthetic_candles(300, seed=9)
    fc = make_forecast(df, FakeForecaster(), 200, 5, 4)
    save_forecast(conn, "X", fc, interval="1h", sampling=config.SamplingConfig(temperature=1.25, top_p=0.8, top_k=3))
    save_forecast(conn, "X", fc, interval="1d")
    assert len(load_forecast_runs(conn, "X")) == 2
    hourly = load_forecast_runs(conn, "X", "1h")
    daily = load_forecast_runs(conn, "X", "1d")
    assert list(hourly["interval"]) == ["1h"] and list(daily["interval"]) == ["1d"]
    assert hourly["temperature"].iloc[0] == pytest.approx(1.25)
    assert hourly["top_p"].iloc[0] == pytest.approx(0.8) and int(hourly["top_k"].iloc[0]) == 3
    assert daily["temperature"].iloc[0] == pytest.approx(1.0)  # defaults are recorded too


def test_a_calibration_is_never_applied_to_a_different_interval(monkeypatch):
    from app import services

    def fake_runs():
        return [{"symbol": "X", "model": "baseline-bootstrap", "run_dir": "/tmp/run", "config": {"interval": "1h"},
                 "calibration": [{"horizon": 7, "factor": 2.5, "fit_end_timestamp": "2020-01-01"}]}]

    monkeypatch.setattr(services, "calibration_runs", fake_runs)
    assert services.active_interval_factor("X", "baseline-bootstrap", 7, interval="1d")[0] == 1.0
    assert services.active_interval_factor("X", "baseline-bootstrap", 7, interval="1h")[0] == 2.5
    # a legacy run with no interval field is treated as daily, not as the env default
    monkeypatch.setattr(services, "calibration_runs", lambda: [
        {"symbol": "X", "model": "baseline-bootstrap", "run_dir": "/tmp/run", "config": {},
         "calibration": [{"horizon": 7, "factor": 1.7, "fit_end_timestamp": "2020-01-01"}]}])
    assert services.active_interval_factor("X", "baseline-bootstrap", 7, interval="1d")[0] == 1.7
    assert services.active_interval_factor("X", "baseline-bootstrap", 7, interval="1h")[0] == 1.0
