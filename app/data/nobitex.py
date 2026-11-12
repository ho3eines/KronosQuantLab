"""Nobitex public OHLC: no token, no account, no order code.

Docs (``GET /market/udf/history``)::

    https://apiv2.nobitex.ir/market/udf/history?symbol=BTCIRT&resolution=D&from=...&to=...

    {"s": "ok", "t": [...], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}

Facts this adapter is built around:

* at most **500 candles per response**, and an undocumented paging parameter
  ``page`` exists; this adapter never relies on it.  It walks **backwards** in
  explicit ``from``/``to`` time windows (newest first), so each request is
  unambiguous and an empty early window cannot hide later data;
* ``s`` can also be ``"no_data"`` (nothing in the window) or ``"error"`` with a
  message in ``errmsg``; both are handled explicitly instead of being parsed;
* the venue reports **base volume only**.  ``amount`` (quote volume) is therefore
  derived as ``volume * close`` and the result is labelled as derived, so nobody
  mistakes it for reported turnover;
* bar boundaries follow the venue (Iran time), so timestamps are kept exactly as
  returned; the venue is marked "not on a UTC grid" and its gaps are reported,
  not patched.

There is deliberately no authentication: no API key is read anywhere in this
module, and the only HTTP call is a public GET.
"""
from __future__ import annotations

import datetime as dt
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from typing import Any

import pandas as pd

from app.core import config, timeframes, venues
from app.core.errors import DataValidationError
from app.data import http

Fetcher = Callable[[str], Any]
RESOLUTIONS: dict[str, str] = {"1h": "60", "4h": "240", "1d": "D"}
MAX_BARS_PER_REQUEST = 500
RETRY_STATUS = (429, 500, 502, 503, 504)
COLUMNS = ("t", "o", "h", "l", "c", "v")


class NobitexProvider:
    """Public Nobitex candles for one interval; implements ``MarketDataProvider``."""

    name = "nobitex-public"
    notes = "amount derived as volume * close (the venue reports base volume only)"

    def __init__(
        self,
        interval: str | None = None,
        base_url: str | None = None,
        fetcher: Fetcher | None = None,
        *,
        timeout: float | None = None,
        min_request_interval: float | None = None,
        retries: int | None = None,
        retry_backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        max_bars_per_request: int = MAX_BARS_PER_REQUEST,
        history_start: str | dt.datetime | None = None,
        now: dt.datetime | None = None,
    ) -> None:
        self.interval = timeframes.normalize(interval or config.INTERVAL)
        self.base_url = (base_url or config.NOBITEX_BASE_URL).rstrip("/")
        self.timeout = config.NOBITEX_TIMEOUT if timeout is None else timeout
        self.fetcher: Fetcher = fetcher or (lambda url: http.get_json(url, self.timeout))
        self.min_request_interval = (
            config.NOBITEX_REQUEST_INTERVAL if min_request_interval is None else min_request_interval
        )
        self.retries = max(1, config.NOBITEX_RETRIES if retries is None else int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.sleep = sleep
        self.max_bars_per_request = max(1, int(max_bars_per_request))
        self.history_start = _epoch(history_start or config.NOBITEX_HISTORY_START)
        self.now = now
        self.last_url: str | None = None
        self.n_requests = 0

    @property
    def resolution(self) -> str:
        try:
            return RESOLUTIONS[self.interval]
        except KeyError as exc:  # pragma: no cover - the CLI restricts intervals
            raise DataValidationError(f"Nobitex has no resolution for interval {self.interval}") from exc

    def _url(self, market: str, start_s: int, end_s: int) -> str:
        query = urllib.parse.urlencode(
            {"symbol": market, "resolution": self.resolution, "from": start_s, "to": end_s}
        )
        return f"{self.base_url}/market/udf/history?{query}"

    def _get(self, url: str) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                self.last_url = url
                self.n_requests += 1
                return self.fetcher(url)
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_STATUS:
                    raise DataValidationError(f"could not fetch {url}: HTTP {exc.code}") from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                last = exc
            if attempt + 1 < self.retries:
                self.sleep(self.retry_backoff * (2**attempt))
        raise DataValidationError(f"could not fetch {url}: {last}") from last

    def fetch(self, symbol: str, start_ms: int = 0) -> pd.DataFrame:
        """Candles from ``start_ms`` (UTC ms) to the newest closed bar."""
        venue = venues.venue_name(symbol)
        if venue != "nobitex":
            raise DataValidationError(f"NobitexProvider cannot serve '{symbol}' (venue {venue})")
        market = venues.market_symbol(symbol)
        step = timeframes.step(self.interval)
        step_s = int(step.total_seconds())
        now = self.now or dt.datetime.now(dt.UTC)
        now_s = int(now.timestamp())
        # Walk *backwards* in explicit windows: the newest candles arrive first, an
        # empty early window cannot hide later data, and the undocumented `page`
        # parameter is never relied on.  ``start_ms == 0`` means "whatever history
        # the venue keeps", floored by KQL_NOBITEX_HISTORY_START (2019-01-01).
        end_s = now_s
        start_s = max(int(start_ms) // 1000, self.history_start)
        rows: list[tuple[int, float, float, float, float, float]] = []
        first = True
        while end_s > start_s:
            window_start = max(end_s - (self.max_bars_per_request - 1) * step_s, start_s)
            url = self._url(market, window_start, end_s)
            if not first and self.min_request_interval > 0:  # polite pacing between pages
                self.sleep(self.min_request_interval)
            page = _parse(self._get(url), url)
            first = False
            rows.extend(page)
            end_s = window_start - step_s
        if not rows:
            raise DataValidationError(f"no Nobitex candles for {market} {self.interval} in the requested range")
        deduped = {row[0]: row for row in rows}  # identical overlap at window edges
        return _to_frame(sorted(deduped.values()))


def _epoch(value: str | dt.datetime) -> int:
    if isinstance(value, dt.datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=dt.UTC)
        return int(stamp.timestamp())
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise DataValidationError(f"KQL_NOBITEX_HISTORY_START must be an ISO date, got {value!r}") from exc
    return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)).timestamp())


def _parse(payload: Any, url: str) -> list[tuple[int, float, float, float, float, float]]:
    """Validate the UDF envelope and return numeric rows. Never guesses."""
    if not isinstance(payload, dict):
        raise DataValidationError(f"unexpected Nobitex response from {url}: {str(payload)[:200]}")
    status = payload.get("s")
    if status == "no_data":
        return []
    if status == "error":
        raise DataValidationError(f"Nobitex error at {url}: {payload.get('errmsg')}")
    if status != "ok":
        raise DataValidationError(f"Nobitex response from {url} has status {status!r}")
    arrays: list[list[Any]] = []
    for key in COLUMNS:
        value = payload.get(key)
        if not isinstance(value, list):
            raise DataValidationError(f"Nobitex response from {url} is missing one of {COLUMNS}")
        arrays.append(value)
    lengths = {len(a) for a in arrays}
    if len(lengths) != 1:
        raise DataValidationError(f"Nobitex response from {url} has arrays of different lengths")
    rows: list[tuple[int, float, float, float, float, float]] = []
    for i in range(len(arrays[0])):
        try:
            stamp = int(arrays[0][i])
            values = tuple(float(arrays[j][i]) for j in range(1, 6))
        except (TypeError, ValueError, IndexError) as exc:
            raise DataValidationError(f"malformed Nobitex candle from {url}: {str(arrays[0][i])[:80]}") from exc
        rows.append((stamp, *values))  # type: ignore[arg-type]
    return rows


def _to_frame(rows: list[tuple[int, float, float, float, float, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["t"], unit="s", utc=True)
    df["amount"] = df["close"] * df["volume"]  # derived; see the module docstring
    return df[["timestamp", "open", "high", "low", "close", "volume", "amount"]]
