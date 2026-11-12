"""Alpari path: MetaTrader 5 CSV export -> validated FX candles -> FX windows."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.core import venues
from app.core.errors import ConfigError, DataValidationError
from app.data import alpari, engine
from app.forecast.base import make_window
from app.storage import db

HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"


def mt5_csv(days: str = "2024-01-01", n: int = 10, *, delimiter: str = "\t") -> str:
    stamps = pd.bdate_range(days, periods=n)
    lines = [HEADER.replace("\t", delimiter)]
    for i, ts in enumerate(stamps):
        values = [f"{1.1000 + i * 0.001:.5f}", f"{1.1005 + i * 0.001:.5f}", f"{1.0995 + i * 0.001:.5f}",
                  f"{1.1002 + i * 0.001:.5f}", "100", "0", "2"]
        if delimiter == ";":
            values = [v.replace(".", ",") for v in values if v not in ("100", "0", "2")] + ["100", "0", "2"]
        lines.append(delimiter.join([ts.strftime("%Y.%m.%d"), "00:00:00", *values]))
    return "\n".join(lines) + "\n"


def test_mt5_tab_export_is_parsed_with_derived_amount() -> None:
    df, report = alpari.read_mt5_csv(mt5_csv(), interval="1d")
    assert list(df.columns) == list(alpari.REQUIRED)
    assert len(df) == 10
    assert report["format"] == "mt5" and report["delimiter"] == "tab"
    assert report["volume_column"] == "tickvol" and report["amount_derived"] is True
    assert df["amount"].iloc[0] == pytest.approx(df["close"].iloc[0] * df["volume"].iloc[0])
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_semicolon_export_with_decimal_commas_is_parsed() -> None:
    df, report = alpari.read_mt5_csv(mt5_csv(delimiter=";"), interval="1d")
    assert report["delimiter"] == "semicolon"
    assert df["close"].iloc[0] == pytest.approx(1.1002)
    assert df["volume"].iloc[0] == 100


def test_headerless_export_uses_the_mt5_column_order() -> None:
    text = "\n".join(mt5_csv().splitlines()[1:]) + "\n"
    df, report = alpari.read_mt5_csv(text, interval="1d")
    assert report["header_detected"] is False and len(df) == 10


def test_timezone_offset_is_applied_explicitly() -> None:
    df, report = alpari.read_mt5_csv(mt5_csv(), interval="1d", tz_offset_hours=3)
    assert df["timestamp"].iloc[0] == pd.Timestamp("2023-12-31 21:00", tz="UTC")
    assert "minus 3h" in report["timezone"]


def test_wrong_timeframe_is_refused() -> None:
    hourly = "\n".join([
        HEADER,
        "2024.01.01\t00:00:00\t1.1\t1.2\t1.0\t1.15\t10\t0\t1",
        "2024.01.01\t01:00:00\t1.1\t1.2\t1.0\t1.16\t10\t0\t1",
        "2024.01.01\t02:00:00\t1.1\t1.2\t1.0\t1.17\t10\t0\t1",
    ])
    with pytest.raises(ConfigError, match="apart"):
        alpari.read_mt5_csv(hourly, interval="1d")


def test_looks_like_mt5() -> None:
    assert alpari.looks_like_mt5(mt5_csv())
    assert not alpari.looks_like_mt5("timestamp,open,high,low,close,volume,amount\n2024-01-01,1,1,1,1,1,1\n")


def test_fx_frame_is_stored_with_weekend_warnings_and_forecasts_sessions() -> None:
    df, _ = alpari.read_mt5_csv(mt5_csv(), interval="1d")
    frame = df[list(alpari.REQUIRED)]
    conn = db.connect(":memory:")
    out = engine.store_candles(conn, "ALPARI:EURUSD", frame, "mt5:test.csv", interval="1d",
                               now=dt.datetime(2024, 6, 1, tzinfo=dt.UTC))
    assert out["venue"] == "alpari" and out["calendar"] == "fx" and out["inserted"] == len(frame)
    assert any("gaps are expected" in w for w in out["warnings"])
    stored = engine.load_candles(conn, "ALPARI:EURUSD", "1d")

    window = make_window(stored, len(stored), lookback=5, horizon=3, freq="1D", calendar="fx")
    assert window.actual is None
    assert (window.future_ts.dt.dayofweek < 5).all()
    assert window.future_ts.iloc[0] > stored["timestamp"].iloc[-1].tz_localize(None)

    with pytest.raises(DataValidationError):
        engine.store_candles(db.connect(":memory:"), "ALPARI:EURUSD", frame, "mt5:test.csv", interval="1d",
                             now=dt.datetime(2024, 6, 1, tzinfo=dt.UTC), strict=True)


def test_fx_annualisation_is_used_for_the_venue() -> None:
    assert venues.bars_per_year("1d", "ALPARI:EURUSD") == 252
