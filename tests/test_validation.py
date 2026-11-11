"""P3 threshold calibration: ARI, permutation null, block bootstrap, stability verdicts."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError, DataValidationError
from app.signals.regime import RegimeParams, detect_regime, regime_labels, regime_series
from app.signals.validation import (
    ValidationParams,
    adjusted_rand_index,
    calibrate_thresholds,
    compare_labels,
    default_block_size,
    forward_regime_labels,
)


def regime_switching_series(n: int = 900, seed: int = 3) -> pd.Series:
    """Blocks of persistent trend/volatility: a market state that really persists."""
    rng = np.random.default_rng(seed)
    states: list[int] = []
    while len(states) < n:
        states += [int(rng.integers(0, 3))] * int(rng.integers(40, 120))
    states = np.asarray(states[:n])
    drift = np.array([0.0018, -0.0018, 0.0])[states]
    vol = np.array([0.012, 0.03, 0.05])[states]
    returns = rng.normal(drift, vol)[: n - 1]
    return pd.Series(100 * np.exp(np.concatenate([[0.0], np.cumsum(returns)])))


def random_walk(n: int = 900, seed: int = 4) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.025, n))))


# ------------------------------------------------------------------ ARI
def test_adjusted_rand_index_known_values():
    assert adjusted_rand_index([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0
    assert adjusted_rand_index(["up", "up", "down", "down"], ["a", "a", "b", "b"]) == 1.0  # names do not matter
    assert adjusted_rand_index([0, 0, 0, 0], [0, 0, 0, 0]) == 1.0  # both trivial
    assert adjusted_rand_index([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0
    # known Hubert-Arabie value for these two partitions
    assert adjusted_rand_index([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(-0.5)
    rng = np.random.default_rng(0)
    a, b = rng.integers(0, 3, 50), rng.integers(0, 3, 50)
    assert -1.0 <= adjusted_rand_index(a, b) <= 1.0


def test_compare_labels_ignores_undefined_positions_and_validates_lengths():
    ref = pd.Series(["up|low", "up|low", None, "down|high", "down|high"], dtype=object)
    other = pd.Series(["up|low", "up|low", "up|low", "down|high", "down|high"], dtype=object)
    assert compare_labels(ref, other) == 1.0
    assert compare_labels(pd.Series([None, None], dtype=object), pd.Series([None, None], dtype=object)) is None
    with pytest.raises(DataValidationError, match="same length"):
        compare_labels(pd.Series(["a", "b"]), pd.Series(["a"]))


# ------------------------------------------------------------------ regime labels
def test_regime_series_is_causal_and_matches_detect_regime():
    close = regime_switching_series()
    table = regime_series(close)
    last = table.iloc[-1]
    detected = detect_regime(close)
    assert (last["trend"], last["volatility"]) == (detected.trend, detected.volatility)
    assert last["realized_vol_annual"] == pytest.approx(detected.realized_vol_annual)
    assert last["vol_percentile"] == pytest.approx(detected.vol_percentile)
    # changing the future must not change any earlier label
    tampered = close.copy()
    tampered.iloc[500:] *= 3.0
    labels_a = regime_labels(close)
    labels_b = regime_labels(tampered)
    pd.testing.assert_series_equal(labels_a.iloc[:500], labels_b.iloc[:500])


def test_volatility_percentile_matches_the_documented_mid_rank_formula():
    close = regime_switching_series()
    params = RegimeParams()
    pct = regime_series(close, params).loc[len(close) - 1, "vol_percentile"]
    series = pd.Series(np.log(close.to_numpy())).diff().rolling(params.vol_window).std() * np.sqrt(365)
    hist = series.dropna().iloc[-params.vol_history:]
    current = float(hist.iloc[-1])
    equal = np.isclose(hist, current, rtol=1e-9, atol=1e-12)
    expected = float(((hist < current) & ~equal).mean() + 0.5 * equal.mean())
    assert pct == pytest.approx(expected, abs=0.01)  # exact ties vs isclose differ only in the 4th decimal


def test_forward_labels_look_ahead_by_exactly_the_forward_window():
    close = regime_switching_series()
    forward = forward_regime_labels(close, RegimeParams(), 365.0, 10)
    # the last `forward_window` bars have no forward regime; everything else is labelled
    assert forward.iloc[-10:].isna().all() and forward.iloc[:-10].notna().sum() > 0
    tampered = close.copy()
    tampered.iloc[-1] *= 2.0  # only the final bar changed
    changed = forward_regime_labels(tampered, RegimeParams(), 365.0, 10)
    # bar 899 can only affect the forward labels of bars 889..898
    assert changed.iloc[:-11].equals(forward.iloc[:-11])
    assert changed.iloc[889] != forward.iloc[889]


# ------------------------------------------------------------------ calibration
def test_validation_params_are_validated():
    with pytest.raises(ConfigError):
        ValidationParams(alpha=0)
    with pytest.raises(ConfigError):
        ValidationParams(alpha=1)
    with pytest.raises(ConfigError):
        ValidationParams(n_permutations=1)
    with pytest.raises(ConfigError):
        ValidationParams(n_bootstrap=1)
    with pytest.raises(ConfigError):
        ValidationParams(null_ari_max=2)
    with pytest.raises(ConfigError):
        ValidationParams(forward_window=1)
    with pytest.raises(ConfigError):
        ValidationParams(forward_window=10_000)
    with pytest.raises(ConfigError):
        ValidationParams(interval="5m")
    assert default_block_size(10) >= 2


def test_persistent_regimes_pass_and_a_random_walk_fails():
    structured = calibrate_thresholds(regime_switching_series(),
                                      ValidationParams(n_permutations=25, n_bootstrap=20, seed=11))
    assert structured["passed"] is True
    assert structured["observed_ari"] >= structured["thresholds"]["stability_threshold"]
    assert structured["thresholds"]["null_ari_max_auto"] is True
    assert structured["bootstrap"]["ari_p05"] >= structured["thresholds"]["stability_threshold"]
    assert structured["warnings"] == []

    noise = calibrate_thresholds(random_walk(), ValidationParams(n_permutations=25, n_bootstrap=20, seed=11))
    assert noise["passed"] is False
    assert noise["warnings"] and "chance" in noise["warnings"][0]


def test_calibration_is_deterministic_for_a_seed_and_reports_the_settings():
    params = ValidationParams(n_permutations=10, n_bootstrap=10, seed=5)
    a = calibrate_thresholds(regime_switching_series(), params)
    b = calibrate_thresholds(regime_switching_series(), params)
    assert a["observed_ari"] == b["observed_ari"]
    assert a["null"] == b["null"] and a["bootstrap"] == b["bootstrap"]
    assert a["params"]["n_permutations"] == 10 and a["params"]["n_bootstrap"] == 10
    assert a["params"]["regime"]["trend_window"] == 50


def test_explicit_thresholds_are_used_and_inconsistency_is_reported():
    # a stability threshold below the null bound would let noise pass
    out = calibrate_thresholds(regime_switching_series(),
                               ValidationParams(n_permutations=15, n_bootstrap=10, null_ari_max=0.5,
                                                stability_threshold=0.1, seed=2))
    assert out["thresholds"]["null_ari_max"] == 0.5 and not out["thresholds"]["null_ari_max_auto"]
    assert out["thresholds"]["stability_threshold"] == 0.1
    assert out["thresholds"]["consistent"] is False
    assert out["passed"] is False
    assert any("below the null bound" in w for w in out["warnings"])

    out2 = calibrate_thresholds(regime_switching_series(),
                                ValidationParams(n_permutations=15, n_bootstrap=10, null_ari_max=0.0,
                                                 stability_threshold=0.0, seed=2))
    assert out2["thresholds"]["null_ari_max"] == 0.0
    assert out2["thresholds"]["stability_threshold"] == 0.0
    assert out2["thresholds"]["consistent"] is True
    assert out2["passed"] is True  # explicit, consistent thresholds are honoured


def test_calibration_refuses_short_or_invalid_series():
    with pytest.raises(DataValidationError, match="at least"):
        calibrate_thresholds(pd.Series(np.linspace(100, 110, 40)), ValidationParams(n_permutations=5, n_bootstrap=5))
    bad = random_walk(400)
    bad.iloc[10] = np.nan
    with pytest.raises(DataValidationError, match="finite, positive"):
        calibrate_thresholds(bad, ValidationParams(n_permutations=5, n_bootstrap=5))
