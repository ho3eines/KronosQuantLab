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


def _store_universe(kql, symbols: int = 4, rows: int = 700) -> None:
    from app import services
    from app.data import engine

    conn = services.open_db()
    for i in range(symbols):
        engine.store_candles(conn, f"UNI{i}", engine.synthetic_candles(rows, seed=300 + i, end="2026-10-31"), "test")
    conn.close()


def test_settings_and_models_show_the_documented_configuration(kql, capsys):
    assert kql.main(["settings"]) == 0
    settings = json.loads(capsys.readouterr().out)
    assert settings["binance_primary_url"] == "https://data-api.binance.vision"
    assert settings["binance_fallback_urls"] == ["https://api.binance.com"]
    assert settings["models"]["small"] == {"model_id": "NeoQuasar/Kronos-small",
                                           "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
                                           "parameters": "24.7M", "context_length": 512}
    assert settings["max_context"] == 512 and settings["max_horizon"] == 96
    assert settings["lookback"] == 400 and settings["interval"] == "1d"
    assert kql.main(["models"]) == 0
    out = capsys.readouterr().out
    assert "NeoQuasar/Kronos-small" in out and "NeoQuasar/Kronos-Tokenizer-base" in out
    assert "sample_count=20" in out


def test_validate_command_writes_a_report_and_returns_its_verdict(kql, capsys):
    assert kql.main(["data", "demo", "--rows", "700"]) == 0
    code = kql.main(["validate", "--symbol", S, "--n-permutations", "8", "--n-bootstrap", "8"])
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "observed persistence ARI" in out and "thresholds:" in out
    runs = list(config.REPORTS_DIR.glob("threshold_validation_*"))
    assert len(runs) == 1 and (runs[0] / "threshold_validation.json").is_file()
    report = json.loads((runs[0] / "threshold_validation.json").read_text())
    assert {"passed", "observed_ari", "thresholds", "null", "bootstrap"} <= set(report)
    # explicit thresholds make the verdict predictable
    assert kql.main(["validate", "--symbol", S, "--n-permutations", "8", "--n-bootstrap", "8",
                     "--null-ari-max", "0", "--stability-threshold", "0"]) == 0
    assert len(list(config.REPORTS_DIR.glob("threshold_validation_*"))) == 2


def test_portfolio_command_runs_offline_and_writes_a_run(kql, capsys):
    _store_universe(kql)
    code = kql.main(["portfolio", "--symbols", "UNI0", "UNI1", "UNI2", "UNI3", "--n-symbol-hold", "2",
                     "--n-symbol-drop", "1", "--hold-thresh", "2", "--lookback", "200", "--horizon", "5",
                     "--n-paths", "5", "--rebalance-every", "20", "--account", "1000000",
                     "--backtest-n-symbol-hold", "2", "--backtest-n-symbol-drop", "1",
                     "--time-range", "2026-01-01", "2026-10-31"])
    assert code == 0
    out = capsys.readouterr().out
    assert "effective hold 2" in out and "SYNTHETIC DATA" not in out and "Historical simulation" in out
    runs = list(config.REPORTS_DIR.glob("portfolio_*"))
    assert len(runs) == 1
    summary = json.loads((runs[0] / "portfolio.json").read_text())
    assert summary["symbols"] == ["UNI0", "UNI1", "UNI2", "UNI3"]
    assert summary["config"]["n_symbol_hold"] == 2 and summary["config"]["account"] == 1000000.0
    assert summary["config"]["time_range"] == ["2026-01-01", "2026-10-31"]
    assert kql.main(["portfolio", "--symbols", "UNI0", "UNI1", "--start", "2026-01-01", "--end", "2026-02-01",
                     "--time-range", "2026-01-01", "2026-02-01"]) == 2  # ambiguous range is refused
    assert summary["effective_hold"] == 2 and summary["metrics"]["strategy"]["n_bars"] > 0
    assert (runs[0] / "equity.csv").is_file() and (runs[0] / "trades.csv").is_file()


def test_interval_workflow_for_intraday_candles(kql, capsys):
    assert kql.main(["data", "demo", "--rows", "300", "--interval", "1h"]) == 0
    assert kql.main(["data", "status", "--interval", "1h"]) == 0
    assert "SYNTH-DEMO" in capsys.readouterr().out
    assert kql.main(["forecast", "--symbol", S, "--interval", "1h", "--horizon", "4", "--lookback", "200",
                     "--n-paths", "4"]) == 0
    out = capsys.readouterr().out
    assert "(1h)" in out and "lookback 200" in out


@pytest.mark.parametrize("argv", [
    ["forecast", "--symbol", S, "--lookback", "513"],
    ["forecast", "--symbol", S, "--horizon", "97"],
    ["forecast", "--symbol", S, "--interval", "5m"],
    ["forecast", "--symbol", S, "--temperature", "0"],
    ["forecast", "--symbol", S, "--top-p", "1.5"],
    ["portfolio", "--symbols", "A", "B", "--account", "-5"],
])
def test_window_sampling_and_interval_limits_are_parse_errors(kql, argv, capsys):
    with pytest.raises(SystemExit) as exc:
        kql.main(argv)
    assert exc.value.code == 2
    assert "Traceback" not in capsys.readouterr().err
