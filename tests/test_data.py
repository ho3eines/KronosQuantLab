from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.core.errors import DataValidationError
from app.data.binance import PAGE_LIMIT, fetch_klines, klines_to_frame
from app.data.validation import require_ok, validate_ohlcv

DAY = 86_400_000


def kline(i: int, close: str = "101.5") -> list:
    t = 1_700_000_000_000 // DAY * DAY + i * DAY
    return [t, "100.0", "102.0", "99.0", close, "12.5", t + DAY - 1, "1262.5", 42, "6", "600", "0"]


def test_klines_to_frame_types_and_units():
    df = klines_to_frame([kline(0), kline(1)])
    assert list(df.columns[:7]) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert df["close"].iloc[0] == 101.5 and df["amount"].iloc[0] == 1262.5
    assert (df["close_time"] - df["timestamp"]).iloc[0] == pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)


def test_fetch_pages_until_short_page():
    pages = [[kline(i) for i in range(PAGE_LIMIT)], [kline(PAGE_LIMIT), kline(PAGE_LIMIT + 1)]]
    urls: list[str] = []

    def fetcher(url: str):
        urls.append(url)
        return pages[len(urls) - 1]

    rows = fetch_klines("BTCUSDT", "1d", "https://example.invalid", fetcher=fetcher)
    assert len(rows) == PAGE_LIMIT + 2 and len(urls) == 2
    assert f"startTime={pages[0][-1][0] + 1}" in urls[1]  # resumes right after the last row


def test_fetch_errors_are_controlled():
    with pytest.raises(DataValidationError):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=lambda u: {"code": -1121, "msg": "bad"})
    with pytest.raises(DataValidationError):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=lambda u: [])

    def boom(url: str):
        raise TimeoutError("no network")

    with pytest.raises(DataValidationError):
        fetch_klines("X", "1d", "https://example.invalid", fetcher=boom)


def test_clean_data_passes(ohlcv):
    clean, rep = validate_ohlcv(ohlcv)
    assert rep["ok"] and rep["rows_out"] == len(ohlcv) and rep["was_sorted"]
    pd.testing.assert_frame_equal(clean, ohlcv)
    require_ok(rep)


def test_sorts_and_drops_duplicates_without_touching_input(ohlcv):
    messy = pd.concat([ohlcv.iloc[::-1], ohlcv.iloc[[5]]], ignore_index=True)
    snapshot = messy.copy()
    clean, rep = validate_ohlcv(messy)
    assert not rep["was_sorted"] and rep["duplicates_dropped"] == 1 and rep["ok"]
    assert clean["timestamp"].is_monotonic_increasing and len(clean) == len(ohlcv)
    pd.testing.assert_frame_equal(messy, snapshot)


def test_incomplete_last_candle_is_dropped(ohlcv):
    last_open = ohlcv["timestamp"].iloc[-1].to_pydatetime()
    clean, rep = validate_ohlcv(ohlcv, now=last_open + dt.timedelta(hours=5))
    assert rep["incomplete_dropped"] == 1 and len(clean) == len(ohlcv) - 1
    _, rep2 = validate_ohlcv(ohlcv, now=last_open + dt.timedelta(days=1))
    assert rep2["incomplete_dropped"] == 0


@pytest.mark.parametrize("mutate,key", [
    (lambda d: d.__setitem__("close", d["close"].where(d.index != 10, np.nan)), "null_rows"),
    (lambda d: d.__setitem__("low", d["low"].where(d.index != 10, -1.0)), "invalid_price_rows"),
    (lambda d: d.__setitem__("high", d["high"].where(d.index != 10, d["low"] * 0.5)), "invalid_price_rows"),
    (lambda d: d.__setitem__("volume", d["volume"].where(d.index != 10, -3.0)), "negative_volume_rows"),
])
def test_bad_rows_are_reported_not_repaired(ohlcv, mutate, key):
    mutate(ohlcv)
    clean, rep = validate_ohlcv(ohlcv)
    assert rep[key] == 1 and not rep["ok"]
    assert len(clean) == len(ohlcv)  # nothing silently removed or filled
    with pytest.raises(DataValidationError):
        require_ok(rep)


def test_gap_detected(ohlcv):
    _, rep = validate_ohlcv(ohlcv.drop(index=[100, 101]))
    assert rep["gaps"] == 1 and not rep["ok"]
    assert rep["gap_examples"][0]["after"].startswith(str(ohlcv["timestamp"].iloc[99].date()))


def test_missing_columns_and_empty(ohlcv):
    with pytest.raises(DataValidationError):
        validate_ohlcv(ohlcv.drop(columns=["amount"]))
    with pytest.raises(DataValidationError):
        validate_ohlcv(ohlcv.iloc[0:0])
