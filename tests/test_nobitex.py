"""Nobitex public OHLC adapter: URL shape, paging, UDF parsing, errors, storage."""
from __future__ import annotations

import datetime as dt
import urllib.error
import urllib.parse

import pandas as pd
import pytest

from app.core.errors import DataValidationError
from app.data import engine
from app.data.nobitex import NobitexProvider
from app.storage import db


class FakeNobitex:
    """Serves the candles of a fixed list that fall inside the requested window."""

    def __init__(self, rows: list[tuple[int, float, float, float, float, float]]) -> None:
        self.rows = rows
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        start, end = int(query["from"][0]), int(query["to"][0])
        selected = [r for r in self.rows if start <= r[0] <= end]
        if not selected:
            return {"s": "no_data"}
        return {
            "s": "ok",
            "t": [r[0] for r in selected],
            "o": [r[1] for r in selected],
            "h": [r[2] for r in selected],
            "l": [r[3] for r in selected],
            "c": [r[4] for r in selected],
            "v": [r[5] for r in selected],
        }


def bars(start: str, n: int, *, price: float = 100.0, volume: float = 2.0) -> list[tuple[int, float, float, float, float, float]]:
    stamps = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return [
        (int(ts.timestamp()), price + i, price + i + 1, price + i - 1, price + i + 0.5, volume + i)
        for i, ts in enumerate(stamps)
    ]


def provider(fetcher: FakeNobitex, interval: str = "1d") -> NobitexProvider:
    return NobitexProvider(interval=interval, fetcher=fetcher, sleep=lambda _s: None, min_request_interval=0,
                           now=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


@pytest.mark.parametrize("interval,resolution", [("1h", "60"), ("4h", "240"), ("1d", "D")])
def test_resolution_mapping(interval: str, resolution: str) -> None:
    assert NobitexProvider(interval=interval).resolution == resolution


def test_fetch_walks_forward_windows_and_derives_amount() -> None:
    rows = bars("2026-10-28", 3)
    fake = FakeNobitex(rows)
    df = provider(fake).fetch("NOBITEX:BTCIRT", 0)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]
    assert len(df) == 3
    assert df["timestamp"].is_monotonic_increasing
    assert df["amount"].iloc[0] == pytest.approx(df["close"].iloc[0] * df["volume"].iloc[0])
    first = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.urls[0]).query)
    assert first["symbol"] == ["BTCIRT"] and first["resolution"] == ["D"]
    assert fake.urls[0].startswith("https://apiv2.nobitex.ir/market/udf/history?")
    assert len(fake.urls) >= 2  # the second window is asked for and comes back empty


def test_no_data_and_error_envelopes_are_reported_not_guessed() -> None:
    with pytest.raises(DataValidationError, match="no Nobitex candles"):
        provider(FakeNobitex([])).fetch("NOBITEX:BTCIRT", 0)
    with pytest.raises(DataValidationError, match="Invalid resolution"):
        provider(lambda _url: {"s": "error", "errmsg": "Invalid resolution!"}).fetch("NOBITEX:BTCIRT", 0)
    broken = {"s": "ok", "t": [1, 2], "o": [1.0], "h": [1.0], "l": [1.0], "c": [1.0], "v": [1.0]}
    with pytest.raises(DataValidationError, match="different lengths"):
        provider(lambda _url: broken).fetch("NOBITEX:BTCIRT", 0)
    with pytest.raises(DataValidationError, match="status"):
        provider(lambda _url: {"s": "weird"}).fetch("NOBITEX:BTCIRT", 0)


def test_provider_refuses_other_venues_and_never_uses_a_token() -> None:
    fake = FakeNobitex(bars("2026-10-28", 2))
    with pytest.raises(DataValidationError, match="cannot serve"):
        provider(fake).fetch("BTCUSDT", 0)
    assert "token" not in str(NobitexProvider(interval="1d")._url("BTCIRT", 0, 10))  # no auth parameter


def test_rate_limit_errors_are_retried() -> None:
    rows = bars("2026-10-28", 2)
    calls = {"n": 0}

    def flaky(url: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        return FakeNobitex(rows)(url)

    sleeps: list[float] = []
    p = NobitexProvider(interval="1d", fetcher=flaky, sleep=sleeps.append, min_request_interval=0,
                        retries=3, retry_backoff=0.5, now=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    df = p.fetch("NOBITEX:BTCIRT", 0)
    assert len(df) == 2
    assert sleeps[:2] == [0.5, 1.0]


def test_venue_native_timestamps_are_stored_with_warnings() -> None:
    conn = db.connect(":memory:")
    stamps = pd.date_range("2026-10-01 19:30", periods=4, freq="D", tz="UTC")  # Iran-midnight style
    frame = pd.DataFrame({
        "timestamp": stamps,
        "open": [10.0, 11, 12, 13], "high": [11.0, 12, 13, 14], "low": [9.0, 10, 11, 12],
        "close": [10.5, 11.5, 12.5, 13.5], "volume": [1.0, 2, 3, 4], "amount": [10.5, 23, 37.5, 54],
    })
    out = engine.store_candles(conn, "NOBITEX:BTCIRT", frame, "test", interval="1d",
                               now=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    assert out["inserted"] == 4 and out["venue"] == "nobitex" and out["calendar"] == "24/7"
    assert any("UTC" in w for w in out["warnings"])
    status = engine.data_status(conn, "1d")[0]
    assert status["venue"] == "nobitex" and status["calendar"] == "24/7"
