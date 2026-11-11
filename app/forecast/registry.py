"""Names -> forecasters. The only place that knows which models exist."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from app.core import config
from app.core.errors import ForecastError, ModelUnavailableError
from app.forecast.base import Forecaster, check_paths
from app.forecast.baselines import BootstrapForecaster

log = logging.getLogger(__name__)
BASELINE = BootstrapForecaster.name
MODEL_NAMES: tuple[str, ...] = (BASELINE, "kronos-small", "kronos-base")


def model_available(name: str) -> tuple[bool, str]:
    if name == BASELINE:
        return True, "built in"
    key = name.removeprefix("kronos-")
    if key not in config.MODELS:
        return False, "unknown model"
    if not (config.KRONOS_SRC_DIR / "model" / "kronos.py").is_file():
        return False, f"Kronos source missing at {config.KRONOS_SRC_DIR}"
    for d in (config.MODELS[key].local_dir, config.TOKENIZER.local_dir):
        if not (d / "config.json").is_file():
            return False, f"weights missing at {d}"
    return True, "weights present"


def build_forecaster(
    name: str, device: str = "cpu", batch_size: int | None = None,
    sampling: config.SamplingConfig | None = None,
) -> Forecaster:
    """Create a forecaster. ``sampling`` only affects the stochastic Kronos models."""
    sampling = sampling or config.SamplingConfig()
    if name == BASELINE:
        return BootstrapForecaster()
    key = name.removeprefix("kronos-")
    if key not in config.MODELS:
        raise ModelUnavailableError(f"unknown model '{name}'. Known: {', '.join(MODEL_NAMES)}")
    from app.forecast.kronos_adapter import KronosForecaster, resolve_device

    resolved, reason = resolve_device(device)
    log.info("device for %s: %s (%s)", name, resolved, reason)
    return KronosForecaster.load(
        name, config.MODELS[key].local_dir, config.TOKENIZER.local_dir, device=resolved,
        batch_size=batch_size, sampling=sampling,
    )


class CachedForecaster:
    """Disk cache around a forecaster, keyed by model + exact context + request.

    Makes slow-model backtests resumable and repeatable. A changed context (even
    one value) is a different key, so stale results cannot be served.
    """

    def __init__(self, inner: Forecaster, cache_dir: Path | None = None) -> None:
        self.inner = inner
        self.name = inner.name
        self.device = getattr(inner, "device", "n/a")
        self.cache_dir = cache_dir or config.FORECAST_CACHE_DIR
        self.sampling = getattr(inner, "sampling", None)
        self.hits = 0
        self.misses = 0

    def _key(self, context: pd.DataFrame, future_ts: pd.Series, n_paths: int, seed: int) -> str:
        h = hashlib.sha256()
        sampling = self.sampling
        sampling_key = f"{sampling.temperature}|{sampling.top_k}|{sampling.top_p}" if sampling else "-"
        h.update(f"{self.name}|{sampling_key}|{n_paths}|{seed}|{len(future_ts)}|{future_ts.iloc[0]}|{future_ts.iloc[-1]}".encode())
        h.update(np.ascontiguousarray(context[list(config.FEATURE_COLUMNS)].to_numpy(dtype=np.float64)).tobytes())
        h.update(str(context["timestamp"].iloc[0]).encode())
        return h.hexdigest()[:32]

    def sample_paths(self, context: pd.DataFrame, future_ts: pd.Series, n_paths: int, seed: int) -> np.ndarray:
        path = self.cache_dir / self.name / f"{self._key(context, future_ts, n_paths, seed)}.npy"
        if path.is_file():
            try:
                cached = check_paths(np.load(path), n_paths, len(future_ts))
            except (OSError, ValueError, EOFError, ForecastError) as exc:  # truncated or foreign file
                log.warning("ignoring unusable cache entry %s: %s", path.name, exc)
            else:
                self.hits += 1
                return cached
        self.misses += 1
        out = self.inner.sample_paths(context, future_ts, n_paths, seed)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npy")
        np.save(tmp, out)
        tmp.replace(path)
        return out
