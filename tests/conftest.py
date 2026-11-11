from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import FEATURE_COLUMNS
from app.core.errors import ForecastError

ROOT = Path(__file__).resolve().parents[1]


def make_ohlcv(n: int = 520, seed: int = 7) -> pd.DataFrame:
    """Small, fixed, SYNTHETIC daily series (seeded random walk) - not market data."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.random(n) * 0.01)
    low = np.minimum(open_, close) * (1 - rng.random(n) * 0.01)
    volume = 10.0 + rng.random(n)
    return pd.DataFrame({
        "timestamp": pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC"),
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume, "amount": volume * close,
    })


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


class FakeForecaster:
    """Deterministic stand-in for a model: seeded random walk from the last close."""

    name = "fake"
    device = "cpu"

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_on_call = fail_on_call

    def sample_paths(self, context, future_ts, n_paths, seed):
        self.calls.append({"last_ts": context["timestamp"].iloc[-1], "first_future": future_ts.iloc[0],
                           "n_context": len(context), "n_paths": n_paths, "seed": seed})
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ForecastError("simulated out of memory")
        rng = np.random.default_rng(seed)
        last = float(context["close"].iloc[-1])
        steps = rng.normal(0, 0.02, (n_paths, len(future_ts)))
        close = last * np.exp(np.cumsum(steps, axis=1))
        out = np.repeat(close[:, :, None], len(FEATURE_COLUMNS), axis=2)
        return out


@pytest.fixture
def fake_forecaster() -> FakeForecaster:
    return FakeForecaster()


@pytest.fixture
def p0(tmp_path, monkeypatch):
    """The CLI module with all artifact paths redirected to a temp dir."""
    from app.core import config

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "DATASETS_DIR", tmp_path / "datasets")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    spec = importlib.util.spec_from_file_location("p0_cli", ROOT / "scripts" / "p0.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
