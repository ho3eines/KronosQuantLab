"""P1 data engine: providers -> validation -> SQLite, plus loading for every other module."""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core import config, timeframes
from app.core.errors import DataValidationError
from app.data import binance
from app.data.validation import require_ok, validate_ohlcv
from app.storage.db import audit

log = logging.getLogger(__name__)
COLS = ["open", "high", "low", "close", "volume", "amount"]


class MarketDataProvider(Protocol):
    name: str

    def fetch(self, symbol: str, start_ms: int) -> pd.DataFrame:
        """Candles from ``start_ms`` (UTC ms) on; columns timestamp + OHLCV + amount."""
        ...


class BinanceProvider:
    """Public spot klines. Read-only market data; there is no account or order code here."""

    name = "binance-public"

    def __init__(
        self, base_urls: str | Sequence[str] | None = None, interval: str | None = None,
        fetcher: binance.Fetcher | None = None,
    ) -> None:
        self.base_urls = binance.endpoint_candidates(base_urls)
        self.interval = timeframes.normalize(interval or config.INTERVAL)
        self.fetcher = fetcher
        self.last_base_url: str | None = None

    def fetch(self, symbol: str, start_ms: int) -> pd.DataFrame:
        rows = binance.fetch_klines(symbol, self.interval, self.base_urls, start_ms, fetcher=self.fetcher)
        self.last_base_url = binance.active_base_url()
        log.debug("%s served %s %s", self.last_base_url, symbol, self.interval)
        return binance.klines_to_frame(rows)


def _resolve_interval(interval: str | None) -> str:
    return timeframes.normalize(interval or config.INTERVAL)


def synthetic_candles(n: int = 900, seed: int = 7, end: str | None = None,
                      interval: str | None = None) -> pd.DataFrame:
    """Seeded geometric random walk. For demos and tests only - NOT market data."""
    if n < 2:
        raise DataValidationError("synthetic series needs at least 2 rows")
    tf = timeframes.get(_resolve_interval(interval))
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.025, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.random(n) * 0.012)
    low = np.minimum(open_, close) * (1 - rng.random(n) * 0.012)
    volume = 1000.0 * (1 + rng.random(n))
    last = (pd.Timestamp(end, tz="UTC") if end
            else pd.Timestamp.now(tz="UTC").floor("D") - tf.step)
    return pd.DataFrame({
        "timestamp": pd.date_range(end=last, periods=n, freq=tf.freq),
        "open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": volume * close,
    })


def last_timestamp(conn: sqlite3.Connection, symbol: str, interval: str | None = None) -> pd.Timestamp | None:
    row = conn.execute(
        "SELECT MAX(ts) AS ts FROM candles WHERE symbol = ? AND interval = ?", (symbol, _resolve_interval(interval))
    ).fetchone()
    return pd.Timestamp(row["ts"]) if row["ts"] else None


def load_candles(conn: sqlite3.Connection, symbol: str, interval: str | None = None) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT ts AS timestamp, open, high, low, close, volume, amount FROM candles "
        "WHERE symbol = ? AND interval = ? ORDER BY ts", conn,
        params=(symbol, _resolve_interval(interval)),
    )
    if df.empty:
        raise DataValidationError(
            f"no {_resolve_interval(interval)} candles stored for {symbol}. Run: python scripts/kql.py data update"
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def store_candles(
    conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, source: str, now: dt.datetime | None = None,
    interval: str | None = None,
) -> dict[str, Any]:
    """Validate and insert. Stored candles are immutable: a differing re-download is
    reported as a conflict and the stored row is kept. Invalid input stores nothing."""
    interval = _resolve_interval(interval)
    tf = timeframes.get(interval)
    now = now or dt.datetime.now(dt.UTC)  # always drop candles that have not closed yet
    clean, report = validate_ohlcv(df, freq=tf.freq, now=now)
    require_ok(report)
    prev = last_timestamp(conn, symbol, interval)
    new = clean if prev is None else clean[clean["timestamp"] > prev]
    if prev is not None and not new.empty and new["timestamp"].iloc[0] != prev + tf.step:
        raise DataValidationError(
            f"{symbol} {interval}: new data starts at {new['timestamp'].iloc[0]} but stored data ends at {prev} (gap)"
        )
    conflicts = 0
    if prev is not None:
        overlap = clean[clean["timestamp"] <= prev]
        if not overlap.empty:
            stored = load_candles(conn, symbol, interval).set_index("timestamp")
            both = overlap.set_index("timestamp").join(stored, rsuffix="_db", how="inner")
            for c in COLS:
                conflicts += int((~np.isclose(both[c], both[f"{c}_db"], rtol=1e-9, atol=0)).sum())
    rows = [(symbol, interval, t.isoformat(), *map(float, vals), source)
            for t, vals in zip(new["timestamp"], new[COLS].to_numpy(), strict=True)]
    with conn:
        conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        result = {"symbol": symbol, "interval": interval, "source": source, "inserted": len(rows),
                  "conflicting_values": conflicts, "incomplete_dropped": report["incomplete_dropped"],
                  "duplicates_dropped": report["duplicates_dropped"], "last": str(last_timestamp(conn, symbol, interval))}
        audit(conn, "data_update", result)
    if conflicts:
        log.warning("%s: %d stored values differ from the provider; stored rows were kept", symbol, conflicts)
    return result


def update_symbol(
    conn: sqlite3.Connection, provider: MarketDataProvider, symbol: str, now: dt.datetime | None = None,
    interval: str | None = None,
) -> dict[str, Any]:
    """Incremental update: fetch from the last stored candle (inclusive, as a consistency check)."""
    interval = _resolve_interval(interval or getattr(provider, "interval", None))
    now = now or dt.datetime.now(dt.UTC)
    prev = last_timestamp(conn, symbol, interval)
    start_ms = 0 if prev is None else int(prev.timestamp() * 1000)
    return store_candles(conn, symbol, provider.fetch(symbol, start_ms), provider.name, now=now, interval=interval)


def data_status(conn: sqlite3.Connection, interval: str | None = None) -> list[dict[str, Any]]:
    interval = _resolve_interval(interval)
    tf = timeframes.get(interval)
    out = []
    for row in conn.execute(
        "SELECT symbol, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, GROUP_CONCAT(DISTINCT source) AS source "
        "FROM candles WHERE interval = ? GROUP BY symbol ORDER BY symbol", (interval,)
    ):
        expected = timeframes.bars_between(row["first"], row["last"], interval)
        stamp = (lambda v: v[:10]) if interval == "1d" else (lambda v: v[:16].replace("T", " "))
        out.append({"symbol": row["symbol"], "interval": interval, "rows": row["n"],
                    "first": stamp(row["first"]), "last": stamp(row["last"]),
                    "missing_bars": expected - row["n"], "step": str(tf.step),
                    "source": row["source"], "synthetic": row["symbol"] == config.SYNTHETIC_SYMBOL})
    return out
