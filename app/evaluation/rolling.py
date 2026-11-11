"""Rolling-origin evaluation on the close price, in time order, without look-ahead."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import CLOSE_INDEX, FEATURE_COLUMNS
from app.core.errors import DataValidationError, ForecastError
from app.evaluation import metrics
from app.forecast.base import Forecaster, make_window

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalConfig:
    lookback: int = 400
    horizons: tuple[int, ...] = (7, 14, 30)
    n_origins: int = 8
    stride: int = 30  # = max horizon, so target windows of different origins do not overlap
    n_paths: int = 20
    seed: int = 20260101

    @property
    def max_horizon(self) -> int:
        return max(self.horizons)


def choose_origins(n_rows: int, cfg: EvalConfig) -> list[int]:
    """Latest ``n_origins`` origins, spaced by ``stride``, returned in chronological order."""
    last = n_rows - cfg.max_horizon
    origins = [last - i * cfg.stride for i in range(cfg.n_origins)]
    origins = sorted(o for o in origins if o - cfg.lookback >= 0)
    if not origins:
        raise DataValidationError(
            f"{n_rows} rows are not enough for lookback={cfg.lookback} + horizon={cfg.max_horizon}"
        )
    return origins


def run_forecasts(df: pd.DataFrame, forecaster: Forecaster, cfg: EvalConfig) -> dict[str, Any]:
    """Sample paths at every origin.

    One run of ``max_horizon`` steps serves all horizons: generation is causal and
    autoregressive, so the first h steps of a longer path have the same
    distribution as an h-step forecast.

    A failing origin is recorded and skipped; it never aborts the whole run.
    """
    origins = choose_origins(len(df), cfg)
    h = cfg.max_horizon
    paths, actual, last_close, used, stamps, seconds, errors = [], [], [], [], [], [], []
    for k, origin in enumerate(origins):
        win = make_window(df, origin, cfg.lookback, h)
        assert win.actual is not None  # guaranteed by choose_origins
        seed = cfg.seed + origin  # identical for every model -> fair comparison
        start = time.perf_counter()
        try:
            p = forecaster.sample_paths(win.context, win.future_ts, cfg.n_paths, seed)
        except ForecastError as exc:
            log.error("origin %d failed for %s: %s", origin, forecaster.name, exc)
            errors.append({"origin": origin, "error": str(exc)})
            continue
        seconds.append(time.perf_counter() - start)
        paths.append(p)
        actual.append(win.actual[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64))
        last_close.append(float(win.context["close"].iloc[-1]))
        used.append(origin)
        stamps.append(str(win.future_ts.iloc[0]))
        log.info("%s origin %d/%d (%s) done in %.1fs", forecaster.name, k + 1, len(origins), stamps[-1], seconds[-1])
    return {
        "model": forecaster.name,
        "origins": used,
        "first_target_timestamp": stamps,
        "paths": np.stack(paths) if paths else np.empty((0, cfg.n_paths, h, len(FEATURE_COLUMNS))),
        "actual": np.stack(actual) if actual else np.empty((0, h, len(FEATURE_COLUMNS))),
        "last_close": np.asarray(last_close),
        "seconds": seconds,
        "errors": errors,
        "n_paths_requested": cfg.n_paths,
        "n_paths_executed": cfg.n_paths if paths else 0,
    }


def _score(y: np.ndarray, f: np.ndarray) -> dict[str, float]:
    return {"mae": metrics.mae(y, f), "rmse": metrics.rmse(y, f), "smape": metrics.smape(y, f), "n": int(y.size)}


def summarize(
    paths: np.ndarray, actual: np.ndarray, last_close: np.ndarray, horizons: tuple[int, ...], model: str
) -> list[dict[str, Any]]:
    """Metric rows per horizon, forecast kind and scope.

    scope ``path``: all steps 1..h of all origins pooled; ``endpoint``: step h only.
    Forecast kinds: ``p50`` (median of paths), ``mean`` (mean of paths, what
    upstream's sample_count returns) and ``naive`` (last observed close, flat).
    """
    if paths.shape[0] == 0:
        return []
    close_paths = paths[..., CLOSE_INDEX]  # (origins, n_paths, H)
    y_all = actual[..., CLOSE_INDEX]  # (origins, H)
    multi = close_paths.shape[1] >= 2
    if multi:
        p10, p50, p90 = metrics.path_quantiles(np.moveaxis(close_paths, 1, 0))
    else:
        p10 = p50 = p90 = close_paths[:, 0, :]
    mean = close_paths.mean(axis=1)
    naive = np.repeat(last_close[:, None], y_all.shape[1], axis=1)
    rows: list[dict[str, Any]] = []
    for h in horizons:
        for scope, sl in (("path", slice(0, h)), ("endpoint", slice(h - 1, h))):
            y = y_all[:, sl]
            for kind, f in (("p50", p50), ("mean", mean), ("naive", naive)):
                row: dict[str, Any] = {"model": model, "horizon": h, "scope": scope, "forecast": kind}
                row.update(_score(y, f[:, sl]))
                row["coverage_p10_p90"] = (
                    metrics.coverage(y, p10[:, sl], p90[:, sl]) if (multi and kind == "p50") else None
                )
                row["n_origins"] = int(y_all.shape[0])
                row["n_paths"] = int(close_paths.shape[1])
                rows.append(row)
    return rows


def endpoint_abs_errors(paths: np.ndarray, actual: np.ndarray, horizon: int) -> np.ndarray:
    """|actual - median path| at step ``horizon`` for every origin (for paired comparison)."""
    close = paths[..., CLOSE_INDEX]
    med = np.median(close, axis=1)[:, horizon - 1]
    return np.abs(actual[:, horizon - 1, CLOSE_INDEX] - med)
