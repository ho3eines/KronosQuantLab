from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.core import config

ROOT = Path(__file__).resolve().parents[1]
S = config.SYNTHETIC_SYMBOL


@pytest.fixture
def kql(tmp_path, monkeypatch):
    for name, value in [("ARTIFACTS_DIR", tmp_path), ("REPORTS_DIR", tmp_path / "reports"),
                        ("DB_PATH", tmp_path / "kql.sqlite3"), ("FORECAST_CACHE_DIR", tmp_path / "cache"),
                        ("MODELS_DIR", tmp_path / "models")]:
        monkeypatch.setattr(config, name, value)
    spec = importlib.util.spec_from_file_location("kql_cli", ROOT / "scripts" / "kql.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_offline_workflow(kql, capsys):
    assert kql.main(["data", "demo", "--rows", "700"]) == 0
    assert kql.main(["data", "status"]) == 0
    assert kql.main(["models"]) == 0
    assert kql.main(["forecast", "--symbol", S, "--horizon", "7"]) == 0
    assert kql.main(["calibrate", "--symbol", S, "--n-origins", "12", "--lookback", "200"]) == 0
    assert kql.main(["backtest", "--symbol", S, "--n-decisions", "8", "--lookback", "200", "--min-edge", "0.001"]) == 0
    assert kql.main(["backtest", "--symbol", S, "--n-decisions", "8", "--lookback", "200"]) == 0
    assert kql.main(["paper", "init"]) == 0
    assert kql.main(["paper", "step", "--symbol", S]) == 0
    assert kql.main(["paper", "status"]) == 0
    out = capsys.readouterr().out
    assert "NOT market data" in out and "SYNTHETIC DATA" in out and "No exchange is contacted" in out
    runs = sorted(config.REPORTS_DIR.glob("backtest_*"))
    assert len(runs) == 2  # re-running never overwrites
    summary = json.loads((runs[0] / "backtest.json").read_text())
    assert summary["synthetic_data"] and "calibration run" in summary["interval_factor_source"]
    assert (runs[0] / "equity.csv").is_file() and len(list(config.REPORTS_DIR.glob("calibration_*"))) == 1


def test_controlled_failures(kql):
    assert kql.main(["forecast", "--symbol", "NOPE"]) == 2  # no data
    assert kql.main(["paper", "step", "--symbol", S]) == 2  # no data / no account
    assert kql.main(["data", "demo"]) == 0
    assert kql.main(["forecast", "--symbol", S, "--model", "kronos-base"]) == 2  # weights not downloaded
    assert kql.main(["paper", "status"]) == 2  # account not initialised
    assert kql.main(["data", "import"]) == 2


def test_dashboard_renders_in_every_data_state(kql):
    """Render-only smoke test. Button handlers are one-line calls into app.services and are
    NOT clicked here (AppTest cannot re-run a page that contains plotly charts)."""
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest

    def render():
        app = AppTest.from_file(str(ROOT / "app" / "ui" / "dashboard.py"), default_timeout=60)
        app.run()
        assert not app.exception, [e.value for e in app.exception]
        return app

    empty = render()  # empty database
    assert any("خالی" in i.value for i in empty.info)
    assert kql.main(["data", "demo", "--rows", "600"]) == 0
    assert kql.main(["forecast", "--symbol", S, "--horizon", "7"]) == 0
    assert kql.main(["calibrate", "--symbol", S, "--n-origins", "10", "--lookback", "200"]) == 0
    assert kql.main(["backtest", "--symbol", S, "--n-decisions", "5", "--lookback", "200", "--min-edge", "0.001"]) == 0
    render()  # data, forecast, calibration, backtest present; no paper account
    assert kql.main(["paper", "init"]) == 0
    assert kql.main(["paper", "step", "--symbol", S]) == 0
    full = render()
    assert any("داده ساختگی" in e.value for e in full.error)  # synthetic data is flagged
    assert {b.label for b in full.button} >= {"تولید پیش‌بینی", "اجرای بک‌تست", "اجرای گام روزانه"}
