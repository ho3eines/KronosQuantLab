from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.config import CLOSE_INDEX
from app.core.errors import DataValidationError, ForecastError, ModelUnavailableError, OverwriteRefusedError
from app.core.runs import new_run_dir, utc_now, write_json_new
from app.evaluation.benchmark import benchmark_forecaster
from app.evaluation.rolling import EvalConfig, choose_origins, run_forecasts, summarize
from app.forecast.base import check_paths, make_window
from tests.conftest import FakeForecaster

CFG = EvalConfig(lookback=100, horizons=(7, 14, 30), n_origins=4, stride=30, n_paths=6)


def test_window_has_no_lookahead(ohlcv):
    win = make_window(ohlcv, origin=200, lookback=100, horizon=30)
    assert len(win.context) == 100 and len(win.future_ts) == 30
    assert win.context["timestamp"].is_monotonic_increasing
    assert win.context["timestamp"].iloc[-1] == ohlcv["timestamp"].iloc[199]
    assert win.context["timestamp"].max() < win.actual["timestamp"].min()
    assert win.future_ts.iloc[0] == ohlcv["timestamp"].iloc[200].tz_localize(None)
    assert win.future_ts.dt.tz is None


def test_window_at_end_has_no_actual_and_bad_windows_fail(ohlcv):
    assert make_window(ohlcv, len(ohlcv), 100, 7).actual is None
    with pytest.raises(DataValidationError):
        make_window(ohlcv, 50, 100, 7)
    with pytest.raises(DataValidationError):
        make_window(ohlcv.drop(index=[150]).reset_index(drop=True), 200, 100, 7)
    with pytest.raises(DataValidationError):
        make_window(ohlcv.iloc[::-1].reset_index(drop=True), 200, 100, 7)


def test_check_paths_contract():
    assert check_paths(np.zeros((2, 7, 6)), 2, 7).shape == (2, 7, 6)
    with pytest.raises(ForecastError):
        check_paths(np.zeros((2, 7, 5)), 2, 7)
    with pytest.raises(ForecastError):
        check_paths(np.full((2, 7, 6), np.nan), 2, 7)


def test_origins_are_chronological_and_fit(ohlcv):
    origins = choose_origins(len(ohlcv), CFG)
    assert origins == sorted(origins) == [400, 430, 460, 490]
    with pytest.raises(DataValidationError):
        choose_origins(120, CFG)


def test_model_only_sees_the_past_and_same_seeds_for_every_model(ohlcv):
    a, b = FakeForecaster(), FakeForecaster()
    ra, rb = run_forecasts(ohlcv, a, CFG), run_forecasts(ohlcv, b, CFG)
    for call, origin in zip(a.calls, ra["origins"]):
        assert call["last_ts"] == ohlcv["timestamp"].iloc[origin - 1]
        assert call["n_context"] == 100 and call["n_paths"] == 6
    assert [c["seed"] for c in a.calls] == [c["seed"] for c in b.calls]
    assert ra["paths"].shape == (4, 6, 30, 6) and ra["actual"].shape == (4, 30, 6)
    np.testing.assert_array_equal(ra["paths"], rb["paths"])
    np.testing.assert_array_equal(ra["actual"][0, :, CLOSE_INDEX], ohlcv["close"].iloc[400:430].to_numpy())


def test_failing_origin_is_recorded_not_fatal(ohlcv):
    res = run_forecasts(ohlcv, FakeForecaster(fail_on_call=2), CFG)
    assert len(res["origins"]) == 3 and len(res["errors"]) == 1
    assert "simulated out of memory" in res["errors"][0]["error"]


def test_summarize_against_hand_computed_values():
    actual = np.zeros((1, 3, 6))
    actual[0, :, CLOSE_INDEX] = [10.0, 12.0, 14.0]
    paths = np.zeros((3, 3, 6))
    paths[:, :, CLOSE_INDEX] = [[9, 10, 11], [10, 12, 14], [11, 14, 20]]
    rows = summarize(paths[None], actual, np.array([10.0]), (3,), "m")
    get = lambda scope, kind: next(r for r in rows if r["scope"] == scope and r["forecast"] == kind)
    assert get("path", "p50")["mae"] == 0.0 and get("path", "p50")["coverage_p10_p90"] == 1.0
    assert get("path", "naive")["mae"] == pytest.approx(2.0)  # |0|,|2|,|4|
    assert get("endpoint", "naive")["rmse"] == pytest.approx(4.0)
    assert get("endpoint", "mean")["mae"] == pytest.approx(1.0)  # mean(11,14,20)=15
    assert get("path", "naive")["coverage_p10_p90"] is None
    assert get("path", "p50")["n"] == 3 and get("endpoint", "p50")["n"] == 1


def test_summarize_empty_and_single_path():
    assert summarize(np.empty((0, 2, 3, 6)), np.empty((0, 3, 6)), np.empty(0), (3,), "m") == []
    rows = summarize(np.ones((2, 1, 3, 6)), np.ones((2, 3, 6)), np.ones(2), (3,), "m")
    assert all(r["coverage_p10_p90"] is None for r in rows)  # no interval from one path


def test_run_dirs_and_files_are_never_overwritten(tmp_path):
    now = utc_now()
    a, b = new_run_dir(tmp_path, "benchmark", now), new_run_dir(tmp_path, "benchmark", now)
    assert a != b and a.is_dir() and b.is_dir()
    write_json_new(a / "r.json", {"v": 1})
    with pytest.raises(OverwriteRefusedError):
        write_json_new(a / "r.json", {"v": 2})
    assert '"v": 1' in (a / "r.json").read_text()
    write_json_new(a / "r.json", {"v": 2}, force=True)
    assert '"v": 2' in (a / "r.json").read_text()


def _bench(factory, ohlcv, **kw):
    win = make_window(ohlcv, len(ohlcv), 100, 7)
    return benchmark_forecaster(factory, win.context, win.future_ts, repeats=2, **kw)


def test_benchmark_records_requested_vs_executed(ohlcv):
    res, raw = _bench(FakeForecaster, ohlcv, stages=(1, 3))
    assert res["status"] == "ok" and res["same_seed_reproducible"] and res["paths_differ_within_batch"]
    assert [s["n_paths"] for s in res["stages"]] == [1, 3] and res["stages"][1]["runs_executed"] == 2
    assert res["max_paths_requested"] == res["max_paths_executed"] == 3 and raw.shape == (3, 7, 6)


def test_benchmark_survives_load_failure(ohlcv):
    def factory():
        raise ModelUnavailableError("weights not found")

    res, raw = _bench(factory, ohlcv)
    assert res["status"] == "load_failed" and "weights not found" in res["error"] and raw is None


def test_benchmark_survives_stage_failure_and_keeps_earlier_stage(ohlcv):
    # calls: warm-up, 2 reproducibility calls, 2 timed runs of stage 1, then stage 2 fails
    res, raw = _bench(lambda: FakeForecaster(fail_on_call=6), ohlcv, stages=(1, 5, 20))
    assert res["status"] == "stage_failed" and res["max_paths_executed"] == 1 and res["max_paths_requested"] == 20
    assert "error" in res["stages"][1] and len(res["stages"]) == 2 and raw.shape == (1, 7, 6)


def test_benchmark_stops_escalating_over_budget(ohlcv):
    res, _ = _bench(FakeForecaster, ohlcv, stages=(1, 5), budget_seconds=-1.0)
    assert len(res["stages"]) == 1 and "budget" in res["stages"][0]["stopped_reason"]
    assert res["max_paths_executed"] == 1 and res["max_paths_requested"] == 5
