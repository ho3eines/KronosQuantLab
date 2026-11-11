from __future__ import annotations

import numpy as np
import pytest

from app.evaluation import metrics


def test_mae_rmse_known_values():
    y, f = np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 5.0])
    assert metrics.mae(y, f) == pytest.approx(1.0)
    assert metrics.rmse(y, f) == pytest.approx(np.sqrt(5 / 3))


def test_smape_definition_and_bounds():
    assert metrics.smape(np.array([100.0]), np.array([110.0])) == pytest.approx(100 * 2 * 10 / 210)
    assert metrics.smape(np.array([5.0]), np.array([5.0])) == 0.0
    assert metrics.smape(np.array([1.0]), np.array([-1.0])) == pytest.approx(200.0)


def test_smape_zero_handling():
    assert metrics.smape(np.array([0.0, 0.0]), np.array([0.0, 0.0])) == 0.0  # both zero -> perfect
    assert metrics.smape(np.array([0.0]), np.array([3.0])) == pytest.approx(200.0)  # one zero -> max
    assert np.isfinite(metrics.smape(np.array([1e-300]), np.array([0.0])))


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        metrics.mae(np.array([1.0, 2.0]), np.array([1.0]))
    with pytest.raises(ValueError):
        metrics.rmse(np.array([]), np.array([]))
    with pytest.raises(ValueError):
        metrics.smape(np.array([np.nan]), np.array([1.0]))


def test_quantiles_and_coverage():
    paths = np.arange(11, dtype=float)[:, None] * np.ones((1, 4))  # 0..10 at each of 4 steps
    p10, p50, p90 = metrics.path_quantiles(paths)
    assert p10 == pytest.approx([1.0] * 4) and p50 == pytest.approx([5.0] * 4) and p90 == pytest.approx([9.0] * 4)
    y = np.array([0.5, 1.0, 9.0, 9.5])  # bounds are inclusive
    assert metrics.coverage(y, p10, p90) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        metrics.path_quantiles(paths[:1])
