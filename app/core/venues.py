"""Venues: symbol namespaces, trading calendars and annualisation.

A symbol stored anywhere in the project is either bare (``BTCUSDT``) and belongs
to the default venue (public Binance spot), or carries an explicit prefix
(``NOBITEX:BTCIRT``, ``ALPARI:EURUSD``).  The prefix is part of the stored
symbol string, so two venues can list the same ticker without colliding in the
``candles`` table, the forecast history or the reports.

Nothing here logs in, holds an account or can place an order: venues only
describe *where public candles come from* and how their calendar behaves.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core import timeframes
from app.core.errors import ConfigError

DEFAULT_VENUE = "binance"
SEPARATOR = ":"
CALENDARS = ("24/7", "fx")  # continuous crypto week vs. Monday-Friday trading week


@dataclass(frozen=True)
class Venue:
    """Everything the rest of the code needs to know about one data venue."""

    name: str
    label: str
    calendar: str  # "24/7" or "fx"
    utc_grid: bool  # bar timestamps sit on UTC interval boundaries
    strict: bool  # off-grid bars and holes make the dataset invalid
    api: bool  # a public, credential-free candle endpoint exists
    example_symbols: tuple[str, ...]
    notes: str = ""


VENUES: dict[str, Venue] = {
    "binance": Venue(
        "binance", "Binance spot (public klines)", "24/7", utc_grid=True, strict=True, api=True,
        example_symbols=("BTCUSDT", "ETHUSDT"),
        notes="data-api.binance.vision first, api.binance.com automatically on HTTP 451/403.",
    ),
    "nobitex": Venue(
        "nobitex", "Nobitex (public OHLC, IRT/USDT markets)", "24/7", utc_grid=False, strict=False, api=True,
        example_symbols=("BTCIRT", "ETHIRT", "BTCUSDT"),
        notes="No token needed. Bar boundaries follow the venue (Iran time), so off-grid bars and gaps "
              "are reported but not fatal. `amount` is derived as volume * close.",
    ),
    "alpari": Venue(
        "alpari", "Alpari (MetaTrader 5 history export)", "fx", utc_grid=False, strict=False, api=False,
        example_symbols=("EURUSD", "XAUUSD", "US30"),
        notes="No public REST market-data API: export the history from MT5 and import it with "
              "'data import --format mt5'. No login, no account, no orders. Weekend/holiday gaps are normal.",
    ),
}
TRADING_DAYS = {"24/7": 365.0, "fx": 252.0}  # bars per year = trading days * bars per trading day


def _clean(text: str) -> str:
    return (text or "").strip()


def split_symbol(symbol: str) -> tuple[str, str]:
    """``"NOBITEX:BTCIRT"`` -> ``("nobitex", "BTCIRT")``; bare symbols -> the default venue."""
    text = _clean(symbol)
    if not text:
        raise ConfigError("empty symbol")
    if SEPARATOR in text:
        head, market = text.split(SEPARATOR, 1)
        name = _clean(head).lower()
        if name not in VENUES:
            raise ConfigError(f"unknown venue '{head.strip()}'. Known venues: {', '.join(VENUES)}")
        market = _clean(market)
        if not market:
            raise ConfigError(f"symbol '{symbol}' has a venue but no market name")
        return name, market
    return DEFAULT_VENUE, text


def join_symbol(venue: str, market: str) -> str:
    name = _clean(venue).lower()
    if name not in VENUES:
        raise ConfigError(f"unknown venue '{venue}'. Known venues: {', '.join(VENUES)}")
    ticker = _clean(market)
    if not ticker:
        raise ConfigError("empty market name")
    return ticker if name == DEFAULT_VENUE else f"{name.upper()}{SEPARATOR}{ticker}"


def normalize_symbol(symbol: str) -> str:
    """Canonical form: ``binance`` symbols stay bare, other venues get an upper-case prefix."""
    venue, market = split_symbol(symbol)
    return join_symbol(venue, market.upper())


def venue_name(symbol: str) -> str:
    return split_symbol(symbol)[0]


def venue_of(symbol: str) -> Venue:
    return VENUES[venue_name(symbol)]


def market_symbol(symbol: str) -> str:
    """The ticker as the venue itself writes it (prefix removed)."""
    return split_symbol(symbol)[1]


def calendar_of(symbol: str) -> str:
    return venue_of(symbol).calendar


def bars_per_year(interval: str | None = None, symbol: str | None = None) -> float:
    """Annualisation factor for a bar series.

    ``24/7`` venues use 365 trading days; FX uses 252, which matters for
    volatility, Sharpe and the regime thresholds (a 365-day year overstates the
    annualised risk of a five-day market by roughly 20%).
    """
    interval = timeframes.normalize(interval or timeframes.DEFAULT_INTERVAL)
    calendar = calendar_of(symbol) if symbol else "24/7"
    bars_per_day = timeframes.bars_per_year(interval) / 365.0
    return float(TRADING_DAYS[calendar] * bars_per_day)


def future_timestamps(last: pd.Timestamp, horizon: int, step: pd.Timedelta, calendar: str) -> pd.DatetimeIndex:
    """Timestamps of the next ``horizon`` bars after ``last``.

    For a 24/7 venue this is a plain arithmetic range.  For an FX calendar the
    weekend is skipped, so a Friday forecast points at Monday, not at Saturday.
    """
    if horizon <= 0:
        raise ConfigError("horizon must be positive")
    if calendar == "24/7":
        return pd.date_range(last + step, periods=horizon, freq=step)
    if calendar != "fx":
        raise ConfigError(f"unknown calendar '{calendar}'")
    out: list[pd.Timestamp] = []
    stamp = pd.Timestamp(last)
    while len(out) < horizon:
        stamp = stamp + step
        if stamp.dayofweek < 5:  # Monday..Friday
            out.append(stamp)
    return pd.DatetimeIndex(out)


def session_deltas_ok(deltas: pd.Series, step: pd.Timedelta, calendar: str) -> bool:
    """Are consecutive bars separated by the bar length and nothing else?

    A 24/7 series must be exactly contiguous.  An FX series may skip weekends
    and holidays, so whole multiples of the bar length are accepted.
    """
    if deltas.empty:
        return True
    if (deltas <= pd.Timedelta(0)).any():
        return False
    if calendar == "24/7":
        return bool((deltas == step).all())
    return bool(((deltas % step) == pd.Timedelta(0)).all())


def describe() -> list[dict[str, object]]:
    """Plain description used by ``kql.py settings`` / ``kql.py data venues``."""
    return [
        {
            "venue": v.name,
            "label": v.label,
            "calendar": v.calendar,
            "utc_grid": v.utc_grid,
            "strict_validation": v.strict,
            "public_api": v.api,
            "symbol_prefix": None if v.name == DEFAULT_VENUE else f"{v.name.upper()}{SEPARATOR}",
            "example_symbols": list(v.example_symbols),
            "notes": v.notes,
        }
        for v in VENUES.values()
    ]
