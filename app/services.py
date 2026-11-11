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
from app.core import config
from app.core.runs import new_run_dir, utc_now, write_json_new
from app.data import engine
from app.evaluation.calibration import calibrate_split
from app.evaluation.rolling import EvalConfig, run_forecasts, summarize
from app.forecast.registry import CachedForecaster, build_forecaster
from app.forecast.service import Forecast, make_forecast, save_forecast
from app.paper import simulator
from app.signals.regime import RegimeParams
from app.signals.rules import SignalParams
from app.storage.db import connect

log = logging.getLogger(__name__)


def open_db() -> sqlite3.Connection:
    return connect(config.DB_PATH)


def get_forecaster(model: str, device: str = "cpu", batch_size: int | None = None, cache: bool = True):
    fc = build_forecaster(model, device, batch_size)
    return CachedForecaster(fc, config.FORECAST_CACHE_DIR) if cache else fc


def forecast_now(conn: sqlite3.Connection, symbol: str, model: str, horizon: int = 30, n_paths: int = 20,
                 lookback: int = 400, device: str = "cpu") -> tuple[Forecast, int]:
    df = engine.load_candles(conn, symbol)
    fc = make_forecast(df, get_forecaster(model, device), lookback, horizon, n_paths)
    return fc, save_forecast(conn, symbol, fc)


def calibrate(conn: sqlite3.Connection, symbol: str, model: str, cfg: EvalConfig, calib_fraction: float = 0.5,
              level: float = 0.8, device: str = "cpu") -> dict[str, Any]:
    """Rolling-origin forecasts on stored data, accuracy vs naive, and split-conformal calibration."""
    df = engine.load_candles(conn, symbol)
    res = run_forecasts(df, get_forecaster(model, device), cfg)
    rows = calibrate_split(res["paths"], res["actual"], cfg.horizons, calib_fraction, level)
    for row in rows:  # last bar whose realised value went into the factor (for look-ahead checks)
        last_origin = res["origins"][row["n_calibration"] - 1] if row["n_calibration"] else None
        row["fit_end_timestamp"] = (
            str(df["timestamp"].iloc[last_origin + row["horizon"] - 1]) if last_origin is not None else None
        )
    out = {
        "kind": "calibration", "created_utc": utc_now().isoformat(), "symbol": symbol, "model": model,
        "config": dataclasses.asdict(cfg), "calib_fraction": calib_fraction, "level": level,
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
    symbol: str, model: str, horizon: int, before: pd.Timestamp | None = None
) -> tuple[float, str]:
    """Newest usable calibration factor for (symbol, model, horizon); 1.0 (raw band) if none.

    ``before``: first decision time of the period the factor will be applied to. A factor
    fitted on data at or after that time would leak the future into a backtest, so it is
    skipped. Runs that do not record their fit end are treated the same way.
    """
    skipped = 0
    for run in calibration_runs():
        if run["symbol"] != symbol or run["model"] != model:
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
    symbol: str, model: str, before: pd.Timestamp | None = None, **overrides: Any
) -> tuple[SignalParams, str]:
    params = SignalParams(**overrides)
    if "interval_factor" in overrides:
        return params, "interval factor set manually"
    factor, source = active_interval_factor(symbol, model, params.horizon, before)
    return dataclasses.replace(params, interval_factor=factor), source


def backtest_start(conn: sqlite3.Connection, symbol: str, cfg: BacktestConfig) -> pd.Timestamp:
    """Timestamp of the first decision bar a backtest with ``cfg`` would use."""
    df = engine.load_candles(conn, symbol)
    first = decision_indices(len(df), cfg, max(RegimeParams().min_bars, 30))[0]
    return pd.Timestamp(df["timestamp"].iloc[first])


def backtest(conn: sqlite3.Connection, symbol: str, model: str, params: SignalParams, cfg: BacktestConfig,
             factor_source: str = "", device: str = "cpu") -> tuple[BacktestResult, dict[str, Any]]:
    df = engine.load_candles(conn, symbol)
    res = run_backtest(df, get_forecaster(model, device), params, cfg)
    summary = {
        "kind": "backtest", "created_utc": utc_now().isoformat(), "symbol": symbol, "model": model,
        "synthetic_data": symbol == config.SYNTHETIC_SYMBOL, "interval_factor_source": factor_source,
        "config": config_dict(cfg, params), "metrics": res.metrics, "errors": res.errors,
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
               device: str = "cpu") -> dict[str, Any]:
    df = engine.load_candles(conn, symbol)
    params, source = signal_params(symbol, model)
    out = simulator.step(conn, symbol, df, get_forecaster(model, device), params, lookback, n_paths)
    out["interval_factor_source"] = source
    age_days = (pd.Timestamp.now(tz="UTC").floor("D") - pd.Timestamp(df["timestamp"].iloc[-1])).days
    if age_days > 1:
        out["warning"] = (f"newest stored candle is {age_days} days old; the decision above is for that old "
                          "candle. Run 'data update' first.")
    return out


def paper_status(conn: sqlite3.Connection) -> dict[str, Any]:
    prices = {s["symbol"]: float(engine.load_candles(conn, s["symbol"])["close"].iloc[-1]) for s in engine.data_status(conn)}
    return simulator.account_status(conn, prices)
