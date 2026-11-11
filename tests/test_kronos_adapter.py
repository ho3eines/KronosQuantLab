"""Adapter tests. The real upstream code is exercised with a tiny RANDOM-weight model
(no download); tests needing torch or the Kronos clone are skipped when those are absent."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core import config
from app.core.errors import ForecastError, ModelUnavailableError
from app.forecast import kronos_adapter as ka
from app.forecast.base import make_window

HAVE_SRC = (config.KRONOS_SRC_DIR / "model" / "kronos.py").is_file()
try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except Exception:  # noqa: BLE001
    HAVE_TORCH = False
needs_kronos = pytest.mark.skipif(not (HAVE_SRC and HAVE_TORCH), reason="torch or vendor/Kronos not available")


def test_missing_source_is_a_controlled_error(tmp_path):
    with pytest.raises(ModelUnavailableError, match="Kronos source not found"):
        ka.import_kronos(tmp_path)


@needs_kronos
def test_missing_weights_is_a_controlled_error(tmp_path):
    with pytest.raises(ModelUnavailableError, match="weights not found"):
        ka.KronosForecaster.load("kronos-small", tmp_path / "nope", tmp_path / "nope")


@pytest.mark.skipif(not HAVE_TORCH, reason="torch not installed")
def test_no_gpu_falls_back_to_cpu(monkeypatch):
    import torch

    assert ka.resolve_device("cpu") == ("cpu", "cpu requested")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert ka.resolve_device("auto")[0] == "cpu"

    def broken() -> bool:
        raise RuntimeError("CUDA driver too old")

    monkeypatch.setattr(torch.cuda, "is_available", broken)
    device, reason = ka.resolve_device("auto")
    assert device == "cpu" and "CUDA driver too old" in reason


@pytest.fixture(scope="module")
def tiny():
    import torch

    k = ka.import_kronos()
    torch.manual_seed(0)
    tok = k.KronosTokenizer(d_in=6, d_model=32, n_heads=2, ff_dim=64, n_enc_layers=1, n_dec_layers=1,
                            ffn_dropout_p=0.1, attn_dropout_p=0.1, resid_dropout_p=0.1, s1_bits=4, s2_bits=4,
                            beta=1.0, gamma0=1.0, gamma=1.0, zeta=1.0, group_size=4)
    model = k.Kronos(s1_bits=4, s2_bits=4, n_layers=1, d_model=32, n_heads=2, ff_dim=64, ffn_dropout_p=0.2,
                     attn_dropout_p=0.1, resid_dropout_p=0.2, token_dropout_p=0.1, learn_te=True)
    return ka.KronosForecaster("tiny-random", model, tok, device="cpu")


@needs_kronos
def test_output_contract_seed_and_separate_paths(tiny, ohlcv):
    win = make_window(ohlcv, 300, 64, 7)
    a = tiny.sample_paths(win.context, win.future_ts, 4, seed=11)
    b = tiny.sample_paths(win.context, win.future_ts, 4, seed=11)
    c = tiny.sample_paths(win.context, win.future_ts, 4, seed=12)
    assert a.shape == (4, 7, 6) and np.isfinite(a).all()
    np.testing.assert_array_equal(a, b)  # same seed -> identical (dropout is off, RNG seeded)
    assert not np.array_equal(a, c)
    assert not np.array_equal(a[0], a[1])  # paths are separate samples, not an average


@needs_kronos
def test_batches_split_and_models_in_eval_mode(tiny, ohlcv):
    win = make_window(ohlcv, 300, 64, 7)
    tiny.batch_size = 2
    try:
        assert tiny.sample_paths(win.context, win.future_ts, 5, seed=1).shape == (5, 7, 6)
    finally:
        tiny.batch_size = None
    assert not tiny._predictor.model.training and not tiny._predictor.tokenizer.training


@needs_kronos
def test_bad_inputs_are_rejected_before_inference(tiny, ohlcv):
    win = make_window(ohlcv, 300, 64, 7)
    with pytest.raises(ForecastError, match="increasing"):
        tiny.sample_paths(win.context.iloc[::-1], win.future_ts, 1, seed=1)
    with pytest.raises(ForecastError, match="follow the context"):
        tiny.sample_paths(win.context, pd.Series(pd.date_range("2000-01-01", periods=7)), 1, seed=1)
    with pytest.raises(ForecastError, match="max_context"):
        tiny.sample_paths(ohlcv.iloc[:513], pd.Series(pd.date_range("2030-01-01", periods=7)), 1, seed=1)
    nan_ctx = win.context.copy()
    nan_ctx.loc[3, "close"] = np.nan
    with pytest.raises(ForecastError, match="NaN"):
        tiny.sample_paths(nan_ctx, win.future_ts, 1, seed=1)


@needs_kronos
def test_load_from_local_directory_without_network(tiny, tmp_path, monkeypatch, ohlcv):
    """save_pretrained -> load(): the same code path as real weights, fully offline."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    tiny._predictor.model.save_pretrained(str(tmp_path / "m"))
    tiny._predictor.tokenizer.save_pretrained(str(tmp_path / "t"))
    assert (tmp_path / "m" / "config.json").is_file() and (tmp_path / "m" / "model.safetensors").is_file()
    fc = ka.KronosForecaster.load("reloaded", tmp_path / "m", tmp_path / "t")
    assert fc.load_seconds is not None and fc.n_parameters == tiny.n_parameters
    assert ka.weights_bytes(tmp_path / "m") > 0
    win = make_window(ohlcv, 300, 64, 7)
    np.testing.assert_array_equal(fc.sample_paths(win.context, win.future_ts, 2, seed=5),
                                  tiny.sample_paths(win.context, win.future_ts, 2, seed=5))


@pytest.mark.checkpoint
@pytest.mark.parametrize("key", ["small", "base"])
def test_real_checkpoint_smoke(key, ohlcv):
    """Runs only where the real weights have been downloaded (never in CI / offline)."""
    spec = config.MODELS[key]
    if not (HAVE_SRC and HAVE_TORCH and (spec.local_dir / "config.json").is_file()):
        pytest.skip(f"real weights for {key} not present in {spec.local_dir}")
    fc = ka.KronosForecaster.load(f"kronos-{key}", spec.local_dir, config.TOKENIZER.local_dir)
    win = make_window(ohlcv, len(ohlcv), 400, 7)
    out = fc.sample_paths(win.context, win.future_ts, 1, seed=1)
    assert out.shape == (1, 7, 6) and np.isfinite(out).all()
