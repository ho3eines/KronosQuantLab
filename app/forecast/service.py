"""P2: produce one probabilistic forecast and persist its quantiles."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import CLOSE_INDEX
from app.core.errors import ForecastError
from app.core.runs import utc_now
from app.evaluation.metrics import path_quantiles
from app.forecast.base import Forecaster, make_window
from app.storage.db import audit


@dataclass(frozen=True)
class Forecast:
    model: str
    origin_ts: pd.Timestamp  # last bar the model saw
    last_close: float
    future_ts: pd.Series
    paths: np.ndarray  # (n_paths, horizon, 6)
    p10: np.ndarray  # close quantiles per step, RAW (uncalibrated)
    p50: np.ndarray
    p90: np.ndarray
    seed: int
    lookback: int

    @property
    def horizon(self) -> int:
        return len(self.future_ts)


def origin_seed(base_seed: int, origin_ts: pd.Timestamp) -> int:
    """Deterministic per-date seed, identical for every model."""
    return base_seed + int(pd.Timestamp(origin_ts).toordinal())


def make_forecast(
    df: pd.DataFrame, forecaster: Forecaster, lookback: int, horizon: int, n_paths: int,
    base_seed: int = 20260101, origin: int | None = None,
) -> Forecast:
    """Forecast the ``horizon`` bars after row ``origin - 1`` (default: after the last row)."""
    if n_paths < 2:
        raise ForecastError("n_paths must be at least 2: quantiles cannot be computed from one path")
    origin = len(df) if origin is None else origin
    lookback = min(lookback, origin)
    win = make_window(df, origin, lookback, horizon)
    origin_ts = pd.Timestamp(win.context["timestamp"].iloc[-1])
    seed = origin_seed(base_seed, origin_ts)
    paths = forecaster.sample_paths(win.context, win.future_ts, n_paths, seed)
    p10, p50, p90 = path_quantiles(paths[..., CLOSE_INDEX])
    return Forecast(forecaster.name, origin_ts, float(win.context["close"].iloc[-1]), win.future_ts,
                    paths, p10, p50, p90, seed, lookback)


def save_forecast(conn: sqlite3.Connection, symbol: str, fc: Forecast) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO forecast_runs (created_utc, symbol, model, origin_ts, last_close, horizon, n_paths, seed, lookback) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (utc_now().isoformat(timespec="seconds"), symbol, fc.model, fc.origin_ts.isoformat(), fc.last_close,
             fc.horizon, int(fc.paths.shape[0]), fc.seed, fc.lookback),
        )
        run_id = int(cur.lastrowid or 0)
        conn.executemany(
            "INSERT INTO forecast_quantiles VALUES (?,?,?,?,?,?)",
            [(run_id, i + 1, str(fc.future_ts.iloc[i]), float(fc.p10[i]), float(fc.p50[i]), float(fc.p90[i]))
             for i in range(fc.horizon)],
        )
        audit(conn, "forecast", {"run_id": run_id, "symbol": symbol, "model": fc.model, "origin_ts": fc.origin_ts})
    return run_id


def load_forecast_runs(conn: sqlite3.Connection, symbol: str | None = None) -> pd.DataFrame:
    q = "SELECT * FROM forecast_runs" + (" WHERE symbol = ?" if symbol else "") + " ORDER BY id DESC"
    return pd.read_sql_query(q, conn, params=(symbol,) if symbol else ())


def load_forecast_quantiles(conn: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT step, ts, p10, p50, p90 FROM forecast_quantiles WHERE run_id = ? ORDER BY step",
                           conn, params=(run_id,))
    df["ts"] = pd.to_datetime(df["ts"])
    return df
