from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from app.core import config
from app.core.errors import ModelUnavailableError
from app.forecast import weights
from tests.conftest import FakeForecaster

EVAL = ["evaluate", "--lookback", "100", "--n-origins", "3", "--n-paths", "5"]


@pytest.fixture
def dataset(p0, ohlcv):
    path = config.DATASETS_DIR / "clean" / "BTCUSDT_1d_20260101T000000Z.csv"
    path.parent.mkdir(parents=True)
    ohlcv.to_csv(path, index=False)
    return path


def fake_factory(p0, monkeypatch, fail: set[str] = frozenset()):
    def factory(key, device, batch_size):
        def build():
            if key in fail:
                raise ModelUnavailableError(f"weights not found for {key}")
            fc = FakeForecaster()
            fc.name = f"kronos-{key}"
            return fc
        return build
    monkeypatch.setattr(p0, "_factory", factory)


def test_evaluate_writes_results_and_rerun_never_overwrites(p0, dataset, monkeypatch):
    fake_factory(p0, monkeypatch)
    assert p0.main(EVAL) == 0
    assert p0.main(EVAL) == 0
    runs = sorted(config.REPORTS_DIR.glob("evaluation_*"))
    assert len(runs) == 2  # second run got its own directory
    first = json.loads((runs[0] / "evaluation.json").read_text())
    assert first["models"]["small"]["n_paths_executed"] == 5 and len(first["paired"]) == 3
    assert first["dataset"]["sha256"] and first["config"]["horizons"] == [7, 14, 30]
    m = pd.read_csv(runs[0] / "metrics.csv")
    assert set(m["model"]) == {"small", "base"} and set(m["forecast"]) == {"p50", "mean", "naive"}
    assert set(m["horizon"]) == {7, 14, 30} and (runs[0] / "paths_small.npz").is_file()
    # identical fake models + identical seeds => identical metrics: the comparison setup is fair
    cols = ["mae", "rmse", "smape"]
    pd.testing.assert_frame_equal(m[m.model == "small"][cols].reset_index(drop=True),
                                  m[m.model == "base"][cols].reset_index(drop=True))


def test_one_model_failing_does_not_crash_the_run(p0, dataset, monkeypatch):
    fake_factory(p0, monkeypatch, fail={"base"})
    assert p0.main(EVAL) == 1
    run = next(config.REPORTS_DIR.glob("evaluation_*"))
    out = json.loads((run / "evaluation.json").read_text())
    assert out["models"]["base"]["status"] == "failed" and out["models"]["small"]["status"] == "ok"
    assert out["paired"] == []


def test_benchmark_smoke_and_report(p0, dataset, monkeypatch):
    fake_factory(p0, monkeypatch)
    assert p0.main(["benchmark", "--smoke", "--lookback", "100"]) == 0
    assert p0.main(["benchmark", "--lookback", "100", "--stages", "1", "2", "--repeats", "1"]) == 0
    assert p0.main(EVAL) == 0
    bench = json.loads((next(config.REPORTS_DIR.glob("benchmark_*")) / "benchmark.json").read_text())
    assert bench["models"]["small"]["raw_output"]["shape"] == [2, 30, 6]
    assert bench["models"]["small"]["raw_output"]["features"] == list(config.FEATURE_COLUMNS)
    assert p0.main(["report"]) == 0
    report = config.REPO_ROOT / "docs" / "P0_model_benchmark.md"
    text = report.read_text(encoding="utf-8")
    assert "| small |" in text and "| base |" in text and "naive" in text and "smoke_" not in text
    assert p0.main(["report"]) == 2  # refuses to overwrite
    assert report.read_text(encoding="utf-8") == text
    assert p0.main(["report", "--force"]) == 0


def test_missing_or_invalid_dataset_is_a_controlled_error(p0, ohlcv):
    assert p0.main(EVAL) == 2  # no dataset at all
    path = config.DATASETS_DIR / "clean" / "BTCUSDT_1d_x.csv"
    path.parent.mkdir(parents=True)
    ohlcv.drop(index=[300]).to_csv(path, index=False)
    assert p0.main(EVAL) == 2  # gap -> refused
    assert not list(config.REPORTS_DIR.glob("evaluation_*")) if config.REPORTS_DIR.exists() else True


def test_data_command_keeps_raw_and_clean_separately(p0, monkeypatch):
    from app.data import binance
    from tests.test_data import kline

    rows = [kline(i) for i in range(5)]
    monkeypatch.setattr(binance, "fetch_klines", lambda *a, **k: rows)
    assert p0.main(["data"]) == 0
    raw = json.loads(next((config.DATASETS_DIR / "raw").glob("*.json")).read_text())
    assert raw["rows"] == rows  # exactly as received
    clean = pd.read_csv(next((config.DATASETS_DIR / "clean").glob("*.csv")))
    assert len(clean) == 5 and list(clean.columns[:7]) == ["timestamp", "open", "high", "low", "close", "volume", "amount"]


def _meta(license_id):
    return lambda spec, api=None: {"repo_id": spec.repo_id, "requested_revision": spec.revision,
                                   "resolved_sha": "abc", "license": license_id,
                                   "files": [{"name": "model.safetensors", "bytes": 1000}], "total_bytes": 1000}


def test_models_never_downloads_without_explicit_consent(p0, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(weights, "inspect_repo", _meta("mit"))
    monkeypatch.setattr(weights, "download", lambda spec, meta: calls.append(spec.key) or spec.local_dir)
    assert p0.main(["models"]) == 0 and calls == []
    assert p0.main(["models", "--download"]) == 2 and calls == []
    assert p0.main(["models", "--download", "--yes"]) == 0 and calls == ["tokenizer", "small", "base"]
    assert "license: mit" in capsys.readouterr().out


def test_models_unknown_license_and_low_disk_block_download(p0, monkeypatch):
    calls = []
    monkeypatch.setattr(weights, "download", lambda spec, meta: calls.append(spec.key) or spec.local_dir)
    monkeypatch.setattr(weights, "inspect_repo", _meta(None))
    assert p0.main(["models", "--download", "--yes"]) == 2 and calls == []
    monkeypatch.setattr(weights, "inspect_repo", _meta("mit"))
    monkeypatch.setattr(weights, "free_bytes", lambda path: 10)
    assert p0.main(["models", "--download", "--yes"]) == 2 and calls == []


def test_inspect_repo_reads_license_sha_and_sizes():
    info = SimpleNamespace(sha="deadbeef", card_data=SimpleNamespace(license="mit"),
                           siblings=[SimpleNamespace(rfilename="model.safetensors", size=100),
                                     SimpleNamespace(rfilename="config.json", size=5)])
    api = SimpleNamespace(model_info=lambda repo, revision, files_metadata: info)
    meta = weights.inspect_repo(config.MODELS["base"], api)
    assert meta["resolved_sha"] == "deadbeef" and meta["license"] == "mit" and meta["total_bytes"] == 105

    def offline(*a, **k):
        raise ConnectionError("no network")

    with pytest.raises(ModelUnavailableError):
        weights.inspect_repo(config.MODELS["base"], SimpleNamespace(model_info=offline))
