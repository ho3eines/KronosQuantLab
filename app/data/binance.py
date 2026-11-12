"""Public, credential-free Binance spot klines. Read-only market data; no account access.

Kline row layout (Binance REST ``GET /api/v3/klines``):
[open_time_ms, open, high, low, close, base_volume, close_time_ms, quote_volume,
 trades, taker_buy_base, taker_buy_quote, ignore]. Times are UTC milliseconds.

Two hosts are used: the public data host ``data-api.binance.vision`` first and
``api.binance.com`` as a fallback.  A geographic block (HTTP 451, or a WAF 403)
on one host is not a reason to give up: the fetch is restarted, from the beginning,
against the next host, and the working host is remembered for the rest of the
process so later symbols do not pay the failed attempt again.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.parse
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from app.core import config
from app.core.errors import DataValidationError
from app.data import http

log = logging.getLogger(__name__)

PAGE_LIMIT = 1000
Fetcher = Callable[[str], Any]
GEO_BLOCK_STATUS = config.BINANCE_GEO_BLOCK_STATUS

# The host that last answered successfully. None = "try the configured order".
_ACTIVE_BASE_URL: str | None = None


class GeoBlockedError(DataValidationError):
    """A market-data host refused the request because of a geographic/legal block."""

    def __init__(self, base_url: str, status: int) -> None:
        super().__init__(f"{base_url} is geo-blocked (HTTP {status})")
        self.base_url = base_url
        self.status = status


def active_base_url() -> str | None:
    """Host that last answered, or ``None`` when no request has succeeded yet."""
    return _ACTIVE_BASE_URL


def reset_active_base_url() -> None:
    """Forget the remembered host (tests, or after a network change)."""
    global _ACTIVE_BASE_URL
    _ACTIVE_BASE_URL = None


def endpoint_candidates(base_urls: str | Sequence[str] | None = None) -> list[str]:
    """Ordered, de-duplicated list of hosts. A remembered working host is tried first."""
    if base_urls is None:
        urls: list[str] = list(config.BINANCE_BASE_URLS)
    elif isinstance(base_urls, str):
        urls = [base_urls]
    else:
        urls = list(base_urls)
    clean = [u.strip().rstrip("/") for u in urls if u and u.strip()]
    if not clean:
        raise DataValidationError("no Binance market-data host is configured")
    clean = list(dict.fromkeys(clean))
    if _ACTIVE_BASE_URL in clean:
        clean.remove(_ACTIVE_BASE_URL)
        clean.insert(0, _ACTIVE_BASE_URL)
    return clean


def _http_get_json(url: str) -> Any:
    return http.get_json(url, timeout=30)


def _klines_url(base_url: str, symbol: str, interval: str, start_ms: int) -> str:
    query = urllib.parse.urlencode(
        {"symbol": symbol, "interval": interval, "startTime": start_ms, "limit": PAGE_LIMIT}
    )
    return f"{base_url}/api/v3/klines?{query}"


def _fetch_from(
    base_url: str, symbol: str, interval: str, start_ms: int, max_pages: int, fetcher: Fetcher
) -> list[list[Any]]:
    """Page forward from ``start_ms`` against one host and return the raw rows."""
    rows: list[list[Any]] = []
    cursor = start_ms
    for _ in range(max_pages):
        url = _klines_url(base_url, symbol, interval, cursor)
        try:
            page = fetcher(url)
        except urllib.error.HTTPError as exc:
            if exc.code in GEO_BLOCK_STATUS:
                raise GeoBlockedError(base_url, exc.code) from exc
            raise DataValidationError(f"could not fetch {url}: HTTP {exc.code}") from exc
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
        raise DataValidationError(f"no klines returned for {symbol} {interval} from {base_url}")
    return rows


def fetch_klines(
    symbol: str,
    interval: str,
    base_urls: str | Sequence[str] | None = None,
    start_ms: int = 0,
    max_pages: int = 20,
    fetcher: Fetcher | None = None,
) -> list[list[Any]]:
    """Page forward from ``start_ms``, switching host automatically on a geo block.

    A failed/blocked host is restarted from the original ``start_ms``: rows from two
    hosts are never mixed inside one series.  ``fetcher`` is resolved at call time so
    tests can substitute one without touching the network.
    """
    fetcher = fetcher or _http_get_json
    candidates = endpoint_candidates(base_urls)
    failures: list[str] = []
    for base_url in candidates:
        try:
            rows = _fetch_from(base_url, symbol, interval, start_ms, max_pages, fetcher)
        except GeoBlockedError as exc:
            failures.append(f"{base_url}: HTTP {exc.status} (geo block)")
            log.warning("market-data host %s is geo-blocked (HTTP %d); trying the next host",
                        base_url, exc.status)
            continue
        global _ACTIVE_BASE_URL
        if _ACTIVE_BASE_URL != base_url:
            log.info("using market-data host %s for %s", base_url, symbol)
        _ACTIVE_BASE_URL = base_url
        return rows
    raise DataValidationError(
        "no Binance market-data host answered: " + "; ".join(failures)
        + ". Set KQL_BINANCE_BASE_URL / KQL_BINANCE_FALLBACK_URLS or use 'data import --csv'."
    )


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
