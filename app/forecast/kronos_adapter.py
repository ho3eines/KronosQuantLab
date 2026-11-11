"""Adapter around the *unmodified* upstream Kronos code (shiyu-coder/Kronos).

Verified facts this adapter relies on (upstream model/kronos.py, pinned commit):

* ``KronosPredictor.predict(..., sample_count=N)`` averages the N sampled paths
  and returns only the mean, so it cannot give quantiles.  We call
  ``predict_batch`` with the same series repeated N times and ``sample_count=1``;
  every batch element is then one separate sampled path.
* Normalisation is a z-score fitted on the lookback window only (no look-ahead).
* There is no seed argument; sampling uses torch's global generator
  (``torch.multinomial``), so we call ``torch.manual_seed`` before each call.
* ``KronosPredictor`` never calls ``.eval()``; we do, so dropout is off.

torch is imported lazily so the rest of the project works without it.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import FEATURE_COLUMNS, KRONOS_SRC_DIR, MAX_CONTEXT, SamplingConfig
from app.core.errors import ForecastError, ModelUnavailableError
from app.forecast.base import check_paths

log = logging.getLogger(__name__)


def import_torch() -> Any:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - broken installs raise many types
        raise ModelUnavailableError(f"PyTorch is not usable: {type(exc).__name__}: {exc}") from exc
    return torch


def resolve_device(requested: str = "cpu") -> tuple[str, str]:
    """Return ``(device, reason)``. CUDA is used only if a real tensor op succeeds on it."""
    if requested == "cpu":
        return "cpu", "cpu requested"
    torch = import_torch()
    try:
        if not torch.cuda.is_available():
            return "cpu", "CUDA not available in this PyTorch build / driver"
        x = torch.ones(8, device="cuda:0")
        if float((x * 2).sum().item()) != 16.0:
            return "cpu", "CUDA self-test returned a wrong result"
        return "cuda:0", f"CUDA self-test passed on {torch.cuda.get_device_name(0)}"
    except Exception as exc:  # noqa: BLE001 - unsupported GPUs fail in many ways
        return "cpu", f"CUDA self-test failed: {type(exc).__name__}: {exc}"


def import_kronos(src_dir: Path = KRONOS_SRC_DIR) -> Any:
    """Import upstream's top-level ``model`` package from the pinned clone."""
    if not (src_dir / "model" / "kronos.py").is_file():
        raise ModelUnavailableError(
            f"Kronos source not found at {src_dir}. Clone it (see README) or set KQL_KRONOS_SRC."
        )
    import_torch()
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    try:
        import model as kronos_pkg  # upstream's package really is called "model"
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailableError(f"could not import Kronos code: {type(exc).__name__}: {exc}") from exc
    if not hasattr(kronos_pkg, "KronosPredictor"):
        raise ModelUnavailableError("a different top-level 'model' package shadows Kronos")
    return kronos_pkg


def weights_bytes(model_dir: Path) -> int:
    return sum(p.stat().st_size for p in model_dir.rglob("*") if p.is_file())


class KronosForecaster:
    """Draws separate sample paths from one Kronos checkpoint."""

    def __init__(
        self,
        name: str,
        model: Any,
        tokenizer: Any,
        device: str = "cpu",
        sampling: SamplingConfig = SamplingConfig(),
        max_context: int = MAX_CONTEXT,
        batch_size: int | None = None,
        src_dir: Path = KRONOS_SRC_DIR,
    ) -> None:
        kronos_pkg = import_kronos(src_dir)
        self._torch = import_torch()
        self.name = name
        self.device = device
        self.sampling = sampling
        self.max_context = max_context
        self.batch_size = batch_size
        model.eval()
        tokenizer.eval()
        self.n_parameters = int(sum(p.numel() for p in model.parameters()))
        self._predictor = kronos_pkg.KronosPredictor(
            model, tokenizer, device=device, max_context=max_context
        )
        self.load_seconds: float | None = None

    @classmethod
    def load(
        cls,
        name: str,
        model_dir: Path,
        tokenizer_dir: Path,
        device: str = "cpu",
        src_dir: Path = KRONOS_SRC_DIR,
        **kwargs: Any,
    ) -> "KronosForecaster":
        """Load from local directories only; never touches the network."""
        for d in (model_dir, tokenizer_dir):
            if not (d / "config.json").is_file():
                raise ModelUnavailableError(
                    f"weights not found in {d}. Run: python scripts/p0.py models --download --yes"
                )
        kronos_pkg = import_kronos(src_dir)
        start = time.perf_counter()
        try:
            tokenizer = kronos_pkg.KronosTokenizer.from_pretrained(str(tokenizer_dir))
            model = kronos_pkg.Kronos.from_pretrained(str(model_dir))
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailableError(
                f"failed to load {name} from {model_dir}: {type(exc).__name__}: {exc}"
            ) from exc
        self = cls(name, model, tokenizer, device=device, src_dir=src_dir, **kwargs)
        self.load_seconds = time.perf_counter() - start
        return self

    def sample_paths(
        self, context: pd.DataFrame, future_ts: pd.Series, n_paths: int, seed: int
    ) -> np.ndarray:
        if n_paths <= 0:
            raise ForecastError("n_paths must be positive")
        horizon = len(future_ts)
        x_df = context[list(FEATURE_COLUMNS)].reset_index(drop=True)
        x_ts = pd.to_datetime(context["timestamp"], utc=True).dt.tz_localize(None).reset_index(drop=True)
        y_ts = pd.Series(pd.to_datetime(future_ts)).reset_index(drop=True)
        if not x_ts.is_monotonic_increasing or x_ts.iloc[-1] >= y_ts.iloc[0]:
            raise ForecastError("timestamps must be increasing and the future must follow the context")
        if len(x_df) > self.max_context:
            raise ForecastError(f"context of {len(x_df)} bars exceeds max_context={self.max_context}")

        self._torch.manual_seed(seed)
        chunk = self.batch_size or n_paths
        parts: list[np.ndarray] = []
        try:
            for start in range(0, n_paths, chunk):
                n = min(chunk, n_paths - start)
                frames = self._predictor.predict_batch(
                    df_list=[x_df] * n,
                    x_timestamp_list=[x_ts] * n,
                    y_timestamp_list=[y_ts] * n,
                    pred_len=horizon,
                    T=self.sampling.temperature,
                    top_k=self.sampling.top_k,
                    top_p=self.sampling.top_p,
                    sample_count=1,
                    verbose=False,
                )
                parts.append(np.stack([f[list(FEATURE_COLUMNS)].to_numpy() for f in frames]))
        except (RuntimeError, MemoryError, ValueError) as exc:
            raise ForecastError(f"{self.name} inference failed: {type(exc).__name__}: {exc}") from exc
        return check_paths(np.concatenate(parts, axis=0), n_paths, horizon)
