"""Central configuration. No secrets live here; nothing here talks to a broker.

Every value can be overridden from the process environment (see ``.env.example``).
Nothing in this project needs an API key: the market-data hosts below serve public
candles only.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from app.core import timeframes
from app.core.errors import ConfigError, require

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = Path(os.environ.get("KQL_ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
MODELS_DIR = ARTIFACTS_DIR / "models"
DATASETS_DIR = ARTIFACTS_DIR / "datasets"
REPORTS_DIR = ARTIFACTS_DIR / "reports"

# Upstream Kronos source (no pip package exists): a pinned git clone.
KRONOS_SRC_DIR = Path(os.environ.get("KQL_KRONOS_SRC", REPO_ROOT / "vendor" / "Kronos"))
KRONOS_REPO_URL = "https://github.com/shiyu-coder/Kronos.git"
KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"


# --- Public market data: two hosts, so a geographic block on one is survivable ---
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_optional_float(name: str) -> float | None:
    raw = os.environ.get(name)
    return None if raw is None or not raw.strip() else _env_float(name, 0.0)


def _url_list(raw: str) -> tuple[str, ...]:
    """Split a comma/semicolon/space separated list of URLs, keeping order and de-duplicating."""
    parts = [p.strip().rstrip("/") for p in raw.replace(";", ",").replace(" ", ",").split(",")]
    return tuple(dict.fromkeys(p for p in parts if p))


BINANCE_PRIMARY_URL = (
    os.environ.get("KQL_BINANCE_BASE_URL", "").strip().rstrip("/") or "https://data-api.binance.vision"
)
BINANCE_FALLBACK_URLS = _url_list(
    os.environ.get("KQL_BINANCE_FALLBACK_URLS", "https://api.binance.com")
)
BINANCE_BASE_URLS = tuple(dict.fromkeys((BINANCE_PRIMARY_URL, *BINANCE_FALLBACK_URLS)))
BINANCE_BASE_URL = BINANCE_BASE_URLS[0]  # backward-compatible alias: the primary host
BINANCE_GEO_BLOCK_STATUS = (451, 403)  # 451: legal/geographic block; 403: WAF geo refusal

# --- Columns and model window limits -----------------------------------------
# Column order of Kronos input and output (verified in upstream model/kronos.py).
FEATURE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")
CLOSE_INDEX = FEATURE_COLUMNS.index("close")
MAX_CONTEXT = 512  # upstream README, for Kronos-small and Kronos-base
LOOKBACK = _env_int("KQL_LOOKBACK", 400)  # default model context, at most MAX_CONTEXT
MAX_HORIZON = _env_int("KQL_MAX_HORIZON", 96)  # pred_len ceiling
DEFAULT_PRED_LEN = _env_int("KQL_PRED_LEN", MAX_HORIZON)
require(1 <= LOOKBACK <= MAX_CONTEXT, f"KQL_LOOKBACK must be between 1 and {MAX_CONTEXT}")
require(1 <= MAX_HORIZON <= MAX_CONTEXT, f"KQL_MAX_HORIZON must be between 1 and {MAX_CONTEXT}")
require(1 <= DEFAULT_PRED_LEN <= MAX_HORIZON, f"KQL_PRED_LEN must be between 1 and {MAX_HORIZON}")

TOKENIZER_REPO_ID = "NeoQuasar/Kronos-Tokenizer-base"


@dataclass(frozen=True)
class ModelSpec:
    """One Hugging Face repository. ``revision=None`` means: resolve and record at download."""

    key: str
    repo_id: str
    revision: str | None
    tokenizer_id: str = TOKENIZER_REPO_ID
    parameters: str | None = None  # documented size, informational only
    context_length: int | None = MAX_CONTEXT

    @property
    def local_dir(self) -> Path:
        return MODELS_DIR / self.repo_id.split("/")[-1]

    @property
    def display_name(self) -> str:
        return self.repo_id.split("/")[-1]


# Revisions of small + tokenizer are the ones pinned by upstream's own regression
# test. Upstream pins nothing for base, so it is resolved and written to the
# manifest at download time.
TOKENIZER = ModelSpec("tokenizer", TOKENIZER_REPO_ID, "0e0117387f39004a9016484a186a908917e22426",
                      tokenizer_id=TOKENIZER_REPO_ID, parameters=None, context_length=None)
MODELS: dict[str, ModelSpec] = {
    "small": ModelSpec("small", "NeoQuasar/Kronos-small", "901c26c1332695a2a8f243eb2f37243a37bea320",
                       TOKENIZER_REPO_ID, "24.7M", MAX_CONTEXT),
    "base": ModelSpec("base", "NeoQuasar/Kronos-base", None, TOKENIZER_REPO_ID, "102.3M", MAX_CONTEXT),
}
MODEL_ALIASES: dict[str, str] = {"kronos-small": "small", "kronos-base": "base"}


def model_spec(name: str) -> ModelSpec:
    """Resolve ``kronos-small`` / ``small`` to its repository specification."""
    key = MODEL_ALIASES.get(name, name)
    if key not in MODELS:
        raise ValueError(f"unknown model '{name}'. Known: {', '.join(MODELS)}")
    return MODELS[key]


@dataclass(frozen=True)
class SamplingConfig:
    """Sampling knobs that really exist upstream; defaults = KronosPredictor.predict defaults.

    ``sample_count`` (the number of sampled paths) is a per-call argument, not part of
    this record: see ``DEFAULT_SAMPLE_COUNT``.
    """

    temperature: float = _env_float("KQL_TEMPERATURE", 1.0)
    top_k: int = _env_int("KQL_TOP_K", 0)
    top_p: float = _env_float("KQL_TOP_P", 0.9)

    def __post_init__(self) -> None:
        require(math.isfinite(self.temperature) and self.temperature > 0, "temperature must be positive")
        require(isinstance(self.top_k, int) and self.top_k >= 0, "top_k must be a non-negative integer")
        require(math.isfinite(self.top_p) and 0 < self.top_p <= 1, "top_p must be in (0, 1]")

    def as_plain(self) -> dict[str, float | int]:
        return {"temperature": self.temperature, "top_k": self.top_k, "top_p": self.top_p}


DEFAULT_SAMPLE_COUNT = _env_int("KQL_SAMPLE_COUNT", 20)
require(DEFAULT_SAMPLE_COUNT >= 2, "KQL_SAMPLE_COUNT must be at least 2 (quantiles need several paths)")


# --- P1..P5 ------------------------------------------------------------------
DB_PATH = Path(os.environ.get("KQL_DB_PATH", ARTIFACTS_DIR / "kql.sqlite3"))
FORECAST_CACHE_DIR = ARTIFACTS_DIR / "forecast_cache"
INTERVAL = timeframes.normalize(os.environ.get("KQL_INTERVAL", timeframes.DEFAULT_INTERVAL))
BARS_PER_YEAR = timeframes.bars_per_year(INTERVAL)
TRADING_DAYS_PER_YEAR = int(BARS_PER_YEAR)  # backward-compatible name; derived from INTERVAL
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT",)  # test fixture, not a universe decision
SYNTHETIC_SYMBOL = "SYNTH-DEMO"  # generated random walk; never real market data


@dataclass(frozen=True)
class PortfolioDefaults:
    """Defaults of the Qlib-style cross-sectional simulator (see ``app/backtest/portfolio.py``)."""

    n_symbol_hold: int = _env_int("KQL_N_SYMBOL_HOLD", 50)
    n_symbol_drop: int = _env_int("KQL_N_SYMBOL_DROP", 5)
    hold_thresh: int = _env_int("KQL_HOLD_THRESH", 5)
    account: float = _env_float("KQL_ACCOUNT", 100_000_000.0)


# --- P3 threshold calibration defaults (all overridable from the environment) ------
VALIDATION_ALPHA = _env_float("KQL_VALIDATION_ALPHA", 0.05)
VALIDATION_NULL_ARI_MAX = _env_optional_float("KQL_VALIDATION_NULL_ARI_MAX")
VALIDATION_STABILITY_THRESHOLD = _env_optional_float("KQL_VALIDATION_STABILITY_THRESHOLD")
N_PERMUTATIONS = _env_int("KQL_N_PERMUTATIONS", 100)
N_BOOTSTRAP = _env_int("KQL_N_BOOTSTRAP", 50)
require(0 < VALIDATION_ALPHA < 1, "KQL_VALIDATION_ALPHA must be strictly between 0 and 1")
require(N_PERMUTATIONS >= 2 and N_BOOTSTRAP >= 2, "KQL_N_PERMUTATIONS and KQL_N_BOOTSTRAP must be at least 2")
for _name, _value in (("KQL_VALIDATION_NULL_ARI_MAX", VALIDATION_NULL_ARI_MAX),
                      ("KQL_VALIDATION_STABILITY_THRESHOLD", VALIDATION_STABILITY_THRESHOLD)):
    require(_value is None or -1 <= _value <= 1, f"{_name} must be between -1 and 1")

PORTFOLIO_DEFAULTS = PortfolioDefaults()
require(PORTFOLIO_DEFAULTS.n_symbol_hold >= 1, "KQL_N_SYMBOL_HOLD must be at least 1")
require(1 <= PORTFOLIO_DEFAULTS.n_symbol_drop <= PORTFOLIO_DEFAULTS.n_symbol_hold,
        "KQL_N_SYMBOL_DROP must be between 1 and KQL_N_SYMBOL_HOLD")
require(PORTFOLIO_DEFAULTS.hold_thresh >= 0, "KQL_HOLD_THRESH must not be negative")
require(math.isfinite(PORTFOLIO_DEFAULTS.account) and PORTFOLIO_DEFAULTS.account > 0, "KQL_ACCOUNT must be positive")


def effective_settings() -> dict[str, object]:
    """Everything a user may need to reproduce a run, without secrets (used by ``kql.py settings``)."""
    return {
        "interval": INTERVAL,
        "interval_supported": list(timeframes.SUPPORTED_INTERVALS),
        "bars_per_year": BARS_PER_YEAR,
        "lookback": LOOKBACK,
        "max_context": MAX_CONTEXT,
        "max_horizon": MAX_HORIZON,
        "default_pred_len": DEFAULT_PRED_LEN,
        "default_sample_count": DEFAULT_SAMPLE_COUNT,
        "sampling": SamplingConfig().as_plain(),
        "binance_primary_url": BINANCE_PRIMARY_URL,
        "binance_fallback_urls": list(BINANCE_FALLBACK_URLS),
        "binance_geo_block_status": list(BINANCE_GEO_BLOCK_STATUS),
        "models": {
            key: {"model_id": spec.repo_id, "tokenizer_id": spec.tokenizer_id,
                  "parameters": spec.parameters, "context_length": spec.context_length}
            for key, spec in MODELS.items()
        },
        "tokenizer": {"tokenizer_id": TOKENIZER.repo_id},
        "validation_defaults": {
            "validation_alpha": VALIDATION_ALPHA,
            "validation_null_ari_max": VALIDATION_NULL_ARI_MAX,
            "validation_stability_threshold": VALIDATION_STABILITY_THRESHOLD,
            "n_permutations": N_PERMUTATIONS,
            "n_bootstrap": N_BOOTSTRAP,
        },
        "portfolio_defaults": {
            "n_symbol_hold": PORTFOLIO_DEFAULTS.n_symbol_hold,
            "n_symbol_drop": PORTFOLIO_DEFAULTS.n_symbol_drop,
            "hold_thresh": PORTFOLIO_DEFAULTS.hold_thresh,
            "account": PORTFOLIO_DEFAULTS.account,
        },
        "paths": {"artifacts": str(ARTIFACTS_DIR), "db": str(DB_PATH), "kronos_src": str(KRONOS_SRC_DIR)},
    }
