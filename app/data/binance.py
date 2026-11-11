"""Public, credential-free Binance spot klines. Read-only market data; no account access.

Kline row layout (Binance REST ``GET /api/v3/klines``):
[open_time_ms, open, high, low, close, base_volume, close_time_ms, quote_volume,
 trades, taker_buy_base, taker_buy_quote, ignore]. Times are UTC milliseconds.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from collections.abc import Callable

import pandas as pd

from app.core.errors import DataValidationError

log = logging.getLogger(__name__)

PAGE_LIMIT = 1000
Fetcher = Callable[[str], Any]


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "KronosQuantLab-research"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def fetch_klines(
    symbol: str,
    interval: str,
    base_url: str,
    start_ms: int = 0,
    max_pages: int = 20,
    fetcher: Fetcher = _http_get_json,
) -> list[list[Any]]:
    """Page forward from ``start_ms`` and return the rows exactly as the API sent them."""
    rows: list[list[Any]] = []
    cursor = start_ms
    for _ in range(max_pages):
        query = urllib.parse.urlencode(
            {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": PAGE_LIMIT}
        )
        url = f"{base_url}/api/v3/klines?{query}"
        try:
            page = fetcher(url)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise DataValidationError(f"could not fetch {url}: {exc}") from exc
        if not isinstance(page, list):
            raise DataValidationError(f"unexpected response from {url}: {str(page)[:200]}")
        if not page:
            break
        try:
            first_open, last_open = int(page[0][0]), int(page[-1][0])
        except (TypeError, ValueError, IndexError) as exc:
            raise DataValidationError(f"malformed kline row from {url}: {str(page[0])[:120]}") from exc
        if first_open < cursor or last_open < first_open:
            raise DataValidationError(f"{url} returned rows outside the requested range; refusing to continue")
        rows.extend(page)
        log.info("fetched %d rows (total %d)", len(page), len(rows))
        cursor = last_open + 1
        if len(page) < PAGE_LIMIT:
            break
    if not rows:
        raise DataValidationError(f"no klines returned for {symbol} {interval}")
    return rows


def klines_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    """Type-convert raw rows. No cleaning happens here (see ``validation``)."""
    if any(len(r) < 9 for r in rows):
        raise DataValidationError("kline row with fewer than 9 fields")
    df = pd.DataFrame([r[:9] for r in rows], columns=[
        "open_time_ms", "open", "high", "low", "close", "volume",
        "close_time_ms", "amount", "trades",
    ])
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume", "amount", "close_time", "trades"]]
