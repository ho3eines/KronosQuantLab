"""Venues: symbol namespaces, calendars, annualisation and routing."""
from __future__ import annotations

import pandas as pd
import pytest

from app import services
from app.backtest.portfolio import PortfolioConfig
from app.core import venues
from app.core.errors import ConfigError, KQLError
from app.data import engine
from app.data.nobitex import NobitexProvider


def test_symbol_namespacing_roundtrip() -> None:
    assert venues.split_symbol("BTCUSDT") == ("binance", "BTCUSDT")
    assert venues.split_symbol("NOBITEX:BTCIRT") == ("nobitex", "BTCIRT")
    assert venues.split_symbol("alpari:EURUSD") == ("alpari", "EURUSD")
    assert venues.join_symbol("nobitex", "BTCIRT") == "NOBITEX:BTCIRT"
    assert venues.join_symbol("binance", "ETHUSDT") == "ETHUSDT"
    assert venues.normalize_symbol("nobitex:btcirt") == "NOBITEX:BTCIRT"
    assert venues.market_symbol("ALPARI:XAUUSD") == "XAUUSD"


def test_unknown_or_empty_symbols_are_rejected() -> None:
    with pytest.raises(ConfigError):
        venues.split_symbol("KRAKEN:XXBTZUSD")
    with pytest.raises(ConfigError):
        venues.split_symbol("   ")
    with pytest.raises(ConfigError):
        venues.split_symbol("NOBITEX:")


def test_annualisation_follows_the_venue_calendar() -> None:
    assert venues.bars_per_year("1d", "BTCUSDT") == 365
    assert venues.bars_per_year("4h", "BTCUSDT") == 2190
    assert venues.bars_per_year("1h", "NOBITEX:BTCIRT") == 8760
    assert venues.bars_per_year("1d", "ALPARI:EURUSD") == 252
    assert venues.bars_per_year("4h", "ALPARI:EURUSD") == 252 * 6
    assert venues.bars_per_year("1h", "ALPARI:EURUSD") == 252 * 24
    assert venues.calendar_of("ALPARI:EURUSD") == "fx"
    assert venues.calendar_of("BTCUSDT") == "24/7"


def test_future_timestamps_skip_the_weekend_for_fx() -> None:
    friday = pd.Timestamp("2026-10-30 00:00", tz="UTC")
    step = pd.Timedelta(days=1)
    fx = venues.future_timestamps(friday, 3, step, "fx")
    assert list(fx) == [pd.Timestamp("2026-11-02", tz="UTC"), pd.Timestamp("2026-11-03", tz="UTC"),
                        pd.Timestamp("2026-11-04", tz="UTC")]
    crypto = venues.future_timestamps(friday, 2, step, "24/7")
    assert list(crypto) == [pd.Timestamp("2026-10-31", tz="UTC"), pd.Timestamp("2026-11-01", tz="UTC")]
    with pytest.raises(ConfigError):
        venues.future_timestamps(friday, 1, step, "martian")


def test_session_deltas_accept_weekend_holes_only_for_fx() -> None:
    step = pd.Timedelta(days=1)
    with_hole = pd.Series([step, 3 * step])
    assert venues.session_deltas_ok(with_hole, step, "fx")
    assert not venues.session_deltas_ok(with_hole, step, "24/7")
    assert venues.session_deltas_ok(pd.Series([step, step]), step, "24/7")
    assert not venues.session_deltas_ok(pd.Series([pd.Timedelta(0)]), step, "fx")


def test_provider_for_routes_by_venue_and_refuses_alpari() -> None:
    assert isinstance(engine.provider_for("NOBITEX:BTCIRT", interval="1h"), NobitexProvider)
    assert engine.provider_for("BTCUSDT", interval="1h").name == "binance-public"
    with pytest.raises(KQLError) as exc:
        engine.provider_for("ALPARI:EURUSD", interval="1d")
    assert "MetaTrader 5" in str(exc.value) and "data import" in str(exc.value)


def test_mixed_venue_portfolios_are_refused_before_loading_data() -> None:
    with pytest.raises(KQLError) as exc:
        services.portfolio_backtest(None, ["BTCUSDT", "ALPARI:EURUSD"], "baseline-bootstrap",  # type: ignore[arg-type]
                                    PortfolioConfig(n_symbol_drop=1))
    assert "one venue" in str(exc.value)
