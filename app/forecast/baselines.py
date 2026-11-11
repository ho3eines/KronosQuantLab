"""Model-free probabilistic baseline, so Kronos intervals have something to beat."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import FEATURE_COLUMNS
from app.core.errors import ForecastError


class BootstrapForecaster:
    """Random walk whose daily log-returns are resampled (i.i.d.) from the context window.

    Its median is close to the naive last-value forecast; its spread reflects recent
    realised volatility. Only the close column is meaningful: open is the previous
    close, high/low are max/min of open and close, volume/amount repeat the last bar.
    """

    name = "baseline-bootstrap"
    device = "cpu"

    def sample_paths(self, context: pd.DataFrame, future_ts: pd.Series, n_paths: int, seed: int) -> np.ndarray:
        close = context["close"].to_numpy(dtype=np.float64)
        if len(close) < 3 or (close <= 0).any():
            raise ForecastError("bootstrap baseline needs at least 3 positive closes")
        rets = np.diff(np.log(close))
        rng = np.random.default_rng(seed)
        h = len(future_ts)
        draws = rng.choice(rets, size=(n_paths, h), replace=True)
        c = close[-1] * np.exp(np.cumsum(draws, axis=1))
        o = np.concatenate([np.full((n_paths, 1), close[-1]), c[:, :-1]], axis=1)
        out = np.empty((n_paths, h, len(FEATURE_COLUMNS)))
        out[..., 0], out[..., 1], out[..., 2], out[..., 3] = o, np.maximum(o, c), np.minimum(o, c), c
        out[..., 4] = float(context["volume"].iloc[-1])
        out[..., 5] = float(context["amount"].iloc[-1])
        return out
