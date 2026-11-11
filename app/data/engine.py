"""P1 data engine: providers -> validation -> SQLite, plus loading for every other module."""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core import config
from app.core.errors import DataValidationError
from app.data import binance
from app.data.validation import require_ok, validate_ohlcv
from app.storage.db import audit

log = logging.getLogger(__name__)
COLS = ["open", "high", "low", "close", "volume", "amount"]


class MarketDataProvider(Protocol):
    name: str

    def fetch(self, symbol: str, start_ms: int) -> pd.DataFrame:
        """Daily candles from ``start_ms`` (UTC ms) on; columns timestamp + OHLCV + amount."""
        ...


class BinanceProvider:
    """Public spot klines. Read-only market data; there is no account or order code here."""

    name = "binance-public"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or config.BINANCE_BASE_URL

    def fetch(self, symbol: str, start_ms: int) -> pd.DataFrame:
        return binance.klines_to_frame(binance.fetch_klines(symbol, config.INTERVAL, self.base_url, start_ms))


def synthetic_candles(n: int = 900, seed: int = 7, end: str | None = None) -> pd.DataFrame:
    """Seeded geometric random walk. For demos and tests only - NOT market data."""
    if n < 2:
        raise DataValidationError("synthetic series needs at least 2 rows")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.025, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.random(n) * 0.012)
    low = np.minimum(open_, close) * (1 - rng.random(n) * 0.012)
    volume = 1000.0 * (1 + rng.random(n))
    last = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=1)
    return pd.DataFrame({
        "timestamp": pd.date_range(end=last, periods=n, freq="D"),
        "open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": volume * close,
    })


def last_timestamp(conn: sqlite3.Connection, symbol: str) -> pd.Timestamp | None:
    row = conn.execute(
        "SELECT MAX(ts) AS ts FROM candles WHERE symbol = ? AND interval = ?", (symbol, config.INTERVAL)
    ).fetchone()
    return pd.Timestamp(row["ts"]) if row["ts"] else None


def load_candles(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT ts AS timestamp, open, high, low, close, volume, amount FROM candles "
        "WHERE symbol = ? AND interval = ? ORDER BY ts", conn, params=(symbol, config.INTERVAL),
    )
    if df.empty:
        raise DataValidationError(f"no candles stored for {symbol}. Run: python scripts/kql.py data update")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def store_candles(
    conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, source: str, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Validate and insert. Stored candles are immutable: a differing re-download is
    reported as a conflict and the stored row is kept. Invalid input stores nothing."""
    now = now or dt.datetime.now(dt.UTC)  # always drop candles that have not closed yet
    clean, report = validate_ohlcv(df, now=now)
    require_ok(report)
    prev = last_timestamp(conn, symbol)
    step = pd.Timedelta("1D")
    new = clean if prev is None else clean[clean["timestamp"] > prev]
    if prev is not None and not new.empty and new["timestamp"].iloc[0] != prev + step:
        raise DataValidationError(
            f"{symbol}: new data starts at {new['timestamp'].iloc[0]} but stored data ends at {prev} (gap)"
        )
    conflicts = 0
    if prev is not None:
        overlap = clean[clean["timestamp"] <= prev]
        if not overlap.empty:
            stored = load_candles(conn, symbol).set_index("timestamp")
            both = overlap.set_index("timestamp").join(stored, rsuffix="_db", how="inner")
            for c in COLS:
                conflicts += int((~np.isclose(both[c], both[f"{c}_db"], rtol=1e-9, atol=0)).sum())
    rows = [(symbol, config.INTERVAL, t.isoformat(), *map(float, vals), source)
            for t, vals in zip(new["timestamp"], new[COLS].to_numpy(), strict=True)]
    with conn:
        conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        result = {"symbol": symbol, "source": source, "inserted": len(rows), "conflicting_values": conflicts,
                  "incomplete_dropped": report["incomplete_dropped"], "duplicates_dropped": report["duplicates_dropped"],
                  "last": str(last_timestamp(conn, symbol))}
        audit(conn, "data_update", result)
    if conflicts:
        log.warning("%s: %d stored values differ from the provider; stored rows were kept", symbol, conflicts)
    return result


def update_symbol(
    conn: sqlite3.Connection, provider: MarketDataProvider, symbol: str, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Incremental update: fetch from the last stored candle (inclusive, as a consistency check)."""
    now = now or dt.datetime.now(dt.UTC)
    prev = last_timestamp(conn, symbol)
    start_ms = 0 if prev is None else int(prev.timestamp() * 1000)
    return store_candles(conn, symbol, provider.fetch(symbol, start_ms), provider.name, now=now)


def data_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for row in conn.execute(
        "SELECT symbol, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last, GROUP_CONCAT(DISTINCT source) AS source "
        "FROM candles WHERE interval = ? GROUP BY symbol ORDER BY symbol", (config.INTERVAL,)
    ):
        expected = (pd.Timestamp(row["last"]) - pd.Timestamp(row["first"])).days + 1
        out.append({"symbol": row["symbol"], "rows": row["n"], "first": row["first"][:10], "last": row["last"][:10],
                    "missing_days": expected - row["n"], "source": row["source"],
                    "synthetic": row["symbol"] == config.SYNTHETIC_SYMBOL})
    return out
