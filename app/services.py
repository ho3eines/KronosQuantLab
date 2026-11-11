"""Use-cases shared by the CLI and the dashboard, so neither contains business logic."""
from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestConfig, BacktestResult, config_dict, decision_indices, run_backtest
from app.backtest.portfolio import PortfolioConfig, PortfolioResult, config_dict as portfolio_config_dict
from app.backtest.portfolio import run_portfolio_backtest
from app.core import config, timeframes
from app.core.runs import new_run_dir, utc_now, write_json_new
from app.data import engine
from app.evaluation.calibration import calibrate_split
from app.evaluation.rolling import EvalConfig, run_forecasts, summarize
from app.forecast.registry import CachedForecaster, build_forecaster
from app.forecast.service import Forecast, make_forecast, save_forecast
from app.paper import simulator
from app.signals.regime import RegimeParams
from app.signals.rules import SignalParams
from app.signals.validation import ValidationParams, calibrate_thresholds
from app.storage.db import connect

log = logging.getLogger(__name__)


def open_db() -> sqlite3.Connection:
    return connect(config.DB_PATH)


def get_forecaster(
    model: str, device: str = "cpu", batch_size: int | None = None, cache: bool = True,
    sampling: config.SamplingConfig | None = None,
):
    fc = build_forecaster(model, device, batch_size, sampling=sampling)
    return CachedForecaster(fc, config.FORECAST_CACHE_DIR) if cache else fc


def _interval(interval: str | None) -> str:
    return timeframes.normalize(interval or config.INTERVAL)


def forecast_now(conn: sqlite3.Connection, symbol: str, model: str, horizon: int = 30, n_paths: int = 20,
                 lookback: int = 400, device: str = "cpu", interval: str | None = None,
                 sampling: config.SamplingConfig | None = None) -> tuple[Forecast, int]:
    interval = _interval(interval)
    df = engine.load_candles(conn, symbol, interval)
    fc = make_forecast(df, get_forecaster(model, device, sampling=sampling), lookback, horizon, n_paths,
                       interval=interval)
    return fc, save_forecast(conn, symbol, fc, interval, sampling)


def calibrate(conn: sqlite3.Connection, symbol: str, model: str, cfg: EvalConfig, calib_fraction: float = 0.5,
              level: float = 0.8, device: str = "cpu",
              sampling: config.SamplingConfig | None = None) -> dict[str, Any]:
    """Rolling-origin forecasts on stored data, accuracy vs naive, and split-conformal calibration."""
    df = engine.load_candles(conn, symbol, cfg.interval)
    res = run_forecasts(df, get_forecaster(model, device, sampling=sampling), cfg)
    rows = calibrate_split(res["paths"], res["actual"], cfg.horizons, calib_fraction, level)
    for row in rows:  # last bar whose realised value went into the factor (for look-ahead checks)
        last_origin = res["origins"][row["n_calibration"] - 1] if row["n_calibration"] else None
        row["fit_end_timestamp"] = (
            str(df["timestamp"].iloc[last_origin + row["horizon"] - 1]) if last_origin is not None else None
        )
    out = {
        "kind": "calibration", "created_utc": utc_now().isoformat(), "symbol": symbol, "model": model,
        "config": dataclasses.asdict(cfg), "calib_fraction": calib_fraction, "level": level,
        "sampling": (sampling or config.SamplingConfig()).as_plain(),
        "n_origins_executed": len(res["origins"]), "errors": res["errors"],
        "first_target_timestamp": res["first_target_timestamp"], "calibration": rows,
        "metrics": summarize(res["paths"], res["actual"], res["last_close"], cfg.horizons, model),
    }
    run_dir = new_run_dir(config.REPORTS_DIR, "calibration")
    np.savez_compressed(run_dir / "paths.npz", paths=res["paths"], actual=res["actual"], last_close=res["last_close"])
    write_json_new(run_dir / "calibration.json", out)
    out["run_dir"] = str(run_dir)
    return out


def _load_runs(kind: str) -> list[dict[str, Any]]:
    runs = []
    for d in sorted(config.REPORTS_DIR.glob(f"{kind}_*"), reverse=True):
        f = d / f"{kind}.json"
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            data["run_dir"] = str(d)
            runs.append(data)
    return runs


def calibration_runs() -> list[dict[str, Any]]:
    return _load_runs("calibration")


def backtest_runs() -> list[dict[str, Any]]:
    return _load_runs("backtest")


def active_interval_factor(
    symbol: str, model: str, horizon: int, before: pd.Timestamp | None = None, interval: str | None = None
) -> tuple[float, str]:
    """Newest usable calibration factor for (symbol, model, horizon, interval); 1.0 if none.

    ``before``: first decision time of the period the factor will be applied to. A factor
    fitted on data at or after that time would leak the future into a backtest, so it is
    skipped. Runs that do not record their fit end are treated the same way. A factor
    fitted on a different candle interval is never applied.
    """
    interval = _interval(interval)
    skipped = 0
    for run in calibration_runs():
        if run["symbol"] != symbol or run["model"] != model:
            continue
        if run.get("config", {}).get("interval", "1d") != interval:  # pre-interval runs were daily
            continue
        for row in run["calibration"]:
            if row["horizon"] != horizon or row["factor"] is None:
                continue
            if before is not None:
                fit_end = row.get("fit_end_timestamp")
                if fit_end is None or pd.Timestamp(fit_end) >= pd.Timestamp(before):
                    skipped += 1
                    continue
            return float(row["factor"]), f"calibration run {Path(run['run_dir']).name}"
    if skipped:
        return 1.0, (f"raw, uncalibrated band: {skipped} calibration(s) exist but were fitted on data inside "
                     "the backtest period and would leak the future")
    return 1.0, "no calibration available: raw, uncalibrated P10-P90 band"


def signal_params(
    symbol: str, model: str, before: pd.Timestamp | None = None, interval: str | None = None, **overrides: Any
) -> tuple[SignalParams, str]:
    params = SignalParams(**overrides)
    if "interval_factor" in overrides:
        return params, "interval factor set manually"
    factor, source = active_interval_factor(symbol, model, params.horizon, before, interval)
    return dataclasses.replace(params, interval_factor=factor), source


def backtest_start(conn: sqlite3.Connection, symbol: str, cfg: BacktestConfig) -> pd.Timestamp:
    """Timestamp of the first decision bar a backtest with ``cfg`` would use."""
    df = engine.load_candles(conn, symbol, cfg.interval)
    first = decision_indices(len(df), cfg, max(RegimeParams().min_bars, 30))[0]
    return pd.Timestamp(df["timestamp"].iloc[first])


def backtest(conn: sqlite3.Connection, symbol: str, model: str, params: SignalParams, cfg: BacktestConfig,
             factor_source: str = "", device: str = "cpu",
             sampling: config.SamplingConfig | None = None) -> tuple[BacktestResult, dict[str, Any]]:
    df = engine.load_candles(conn, symbol, cfg.interval)
    res = run_backtest(df, get_forecaster(model, device, sampling=sampling), params, cfg)
    summary = {
        "kind": "backtest", "created_utc": utc_now().isoformat(), "symbol": symbol, "model": model,
        "synthetic_data": symbol == config.SYNTHETIC_SYMBOL, "interval_factor_source": factor_source,
        "config": config_dict(cfg, params), "metrics": res.metrics, "errors": res.errors,
        "sampling": (sampling or config.SamplingConfig()).as_plain(),
        "period": [str(res.equity["timestamp"].iloc[0]), str(res.equity["timestamp"].iloc[-1])],
        "timing": "decide after close of bar t on bars 0..t; execute at open of bar t+1",
        "disclaimer": "Historical simulation under stated assumptions; not a prediction or guarantee of profit.",
    }
    run_dir = new_run_dir(config.REPORTS_DIR, "backtest")
    res.equity.to_csv(run_dir / "equity.csv", index=False)
    pd.DataFrame(res.decisions).to_csv(run_dir / "decisions.csv", index=False)
    pd.DataFrame(res.trades).to_csv(run_dir / "trades.csv", index=False)
    write_json_new(run_dir / "backtest.json", summary)
    summary["run_dir"] = str(run_dir)
    return res, summary


def paper_step(conn: sqlite3.Connection, symbol: str, model: str, n_paths: int = 20, lookback: int = 400,
               device: str = "cpu", interval: str | None = None,
               sampling: config.SamplingConfig | None = None) -> dict[str, Any]:
    interval = _interval(interval)
    df = engine.load_candles(conn, symbol, interval)
    params, source = signal_params(symbol, model, interval=interval)
    out = simulator.step(conn, symbol, df, get_forecaster(model, device, sampling=sampling), params, lookback,
                         n_paths, interval=interval)
    out["interval_factor_source"] = source
    out["sampling"] = (sampling or config.SamplingConfig()).as_plain()
    stale = pd.Timestamp.now(tz="UTC") - pd.Timestamp(df["timestamp"].iloc[-1])
    bars_old = int(stale / timeframes.step(interval))
    if bars_old > 1:
        days_old = stale.total_seconds() / 86_400.0
        out["warning"] = (f"newest stored {interval} candle is {days_old:.1f} days old ({bars_old} bars); "
                          "the decision above is for that old candle. Run 'data update' first.")
    return out


def paper_status(conn: sqlite3.Connection, interval: str | None = None) -> dict[str, Any]:
    interval = _interval(interval)
    prices = {s["symbol"]: float(engine.load_candles(conn, s["symbol"], interval)["close"].iloc[-1])
              for s in engine.data_status(conn, interval)}
    return simulator.account_status(conn, prices)


def validation_runs() -> list[dict[str, Any]]:
    return _load_runs("threshold_validation")


def validate_thresholds(
    conn: sqlite3.Connection, symbol: str, params: ValidationParams = ValidationParams(),
    interval: str | None = None,
) -> dict[str, Any]:
    """Calibrate the P3 regime thresholds on one stored series and write a run report."""
    interval = _interval(interval or params.interval)
    params = dataclasses.replace(params, interval=interval)
    df = engine.load_candles(conn, symbol, interval)
    report = calibrate_thresholds(df["close"], params)
    out: dict[str, Any] = {
        "kind": "threshold_validation", "created_utc": utc_now().isoformat(), "symbol": symbol,
        "synthetic_data": symbol == config.SYNTHETIC_SYMBOL,
        "decision_rule_defaults": {
            **dataclasses.asdict(SignalParams()),
            "note": "placeholders; this report validates the regime labels, not these values",
        },
        **report,
    }
    run_dir = new_run_dir(config.REPORTS_DIR, "threshold_validation")
    write_json_new(run_dir / "threshold_validation.json", out)
    out["run_dir"] = str(run_dir)
    return out


def portfolio_runs() -> list[dict[str, Any]]:
    return _load_runs("portfolio")


def portfolio_backtest(
    conn: sqlite3.Connection, symbols: list[str], model: str, cfg: PortfolioConfig,
    device: str = "cpu", sampling: config.SamplingConfig | None = None,
) -> tuple[PortfolioResult, dict[str, Any]]:
    """Qlib-style cross-sectional backtest over the stored symbols."""
    data = {s: engine.load_candles(conn, s, cfg.interval) for s in symbols}
    res = run_portfolio_backtest(data, get_forecaster(model, device, sampling=sampling), cfg)
    summary = {
        "kind": "portfolio", "created_utc": utc_now().isoformat(), "symbols": list(symbols), "model": model,
        "synthetic_data": any(s == config.SYNTHETIC_SYMBOL for s in symbols),
        "config": portfolio_config_dict(cfg), "metrics": res.metrics, "errors": res.errors,
        "sampling": (sampling or config.SamplingConfig()).as_plain(),
        "period": [str(res.equity["timestamp"].iloc[0]), str(res.equity["timestamp"].iloc[-1])],
        "effective_hold": res.effective_hold,
        "timing": "score after close of bar t on bars 0..t of every symbol; execute at open of bar t+1",
        "disclaimer": "Historical simulation under stated assumptions; not a prediction or guarantee of profit.",
    }
    run_dir = new_run_dir(config.REPORTS_DIR, "portfolio")
    res.equity.to_csv(run_dir / "equity.csv", index=False)
    pd.DataFrame(res.decisions).to_csv(run_dir / "decisions.csv", index=False)
    pd.DataFrame(res.trades).to_csv(run_dir / "trades.csv", index=False)
    write_json_new(run_dir / "portfolio.json", summary)
    summary["run_dir"] = str(run_dir)
    return res, summary
