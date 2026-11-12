"""Local .env support: parsing rules, precedence and config integration."""
from __future__ import annotations

import os
import subprocess
import sys

from app.core import envfile
from tests.conftest import ROOT


def test_parse_env_accepts_comments_quotes_and_export() -> None:
    text = """
# a comment
KQL_LOOKBACK=321
export KQL_INTERVAL="4h"
KQL_ARTIFACTS_DIR='D:\\kql data'   # trailing comment
KQL_BINANCE_BASE_URL=https://data-api.binance.vision
"""
    parsed = envfile.parse_env(text)
    assert parsed == {
        "KQL_LOOKBACK": "321",
        "KQL_INTERVAL": "4h",
        "KQL_ARTIFACTS_DIR": "D:\\kql data",
        "KQL_BINANCE_BASE_URL": "https://data-api.binance.vision",
    }


def test_parse_env_ignores_foreign_keys_and_garbage() -> None:
    text = """
PATH=/usr/bin
KQL_=empty-name
KQL-BAD=not-a-name
KQL_OK=1
just some text
KQL_SPACED = 2
"""
    parsed = envfile.parse_env(text)
    assert parsed == {"KQL_OK": "1", "KQL_SPACED": "2"}


def test_load_env_file_never_overrides_the_environment(tmp_path) -> None:
    file = tmp_path / ".env"
    file.write_text("KQL_LOOKBACK=123\nKQL_INTERVAL=1h\n")
    environ = {"KQL_LOOKBACK": "200"}
    applied = envfile.load_env_file(file, environ)
    assert environ == {"KQL_LOOKBACK": "200", "KQL_INTERVAL": "1h"}
    assert applied == {"KQL_INTERVAL": "1h"}


def test_missing_file_applies_nothing(tmp_path) -> None:
    assert envfile.load_env_file(tmp_path / "nope.env", {}) == {}


def _run_config(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {key: value for key, value in os.environ.items() if not key.startswith("KQL_")}
    clean.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=clean, capture_output=True, text=True)


def test_config_reads_the_env_file(tmp_path) -> None:
    file = tmp_path / ".env"
    file.write_text("KQL_LOOKBACK=123\nKQL_TEMPERATURE=1.5\nKQL_MAX_HORIZON=48\n")
    code = ("import app.core.config as c; print(c.LOOKBACK, c.SamplingConfig().temperature, c.MAX_HORIZON, "
            "c.effective_settings()['paths']['env_file_exists'])")
    out = _run_config(code, {"KQL_ENV_FILE": str(file)})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "123 1.5 48 True"


def test_a_real_environment_variable_wins_over_the_file(tmp_path) -> None:
    file = tmp_path / ".env"
    file.write_text("KQL_LOOKBACK=123\n")
    out = _run_config("import app.core.config as c; print(c.LOOKBACK)",
                      {"KQL_ENV_FILE": str(file), "KQL_LOOKBACK": "200"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "200"
