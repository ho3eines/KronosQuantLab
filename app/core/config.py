"""Central configuration. No secrets live here; nothing here talks to a broker."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = Path(os.environ.get("KQL_ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
MODELS_DIR = ARTIFACTS_DIR / "models"
DATASETS_DIR = ARTIFACTS_DIR / "datasets"
REPORTS_DIR = ARTIFACTS_DIR / "reports"

# Upstream Kronos source (no pip package exists): a pinned git clone.
KRONOS_SRC_DIR = Path(os.environ.get("KQL_KRONOS_SRC", REPO_ROOT / "vendor" / "Kronos"))
KRONOS_REPO_URL = "https://github.com/shiyu-coder/Kronos.git"
KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"

BINANCE_BASE_URL = os.environ.get("KQL_BINANCE_BASE_URL", "https://api.binance.com")

# Column order of Kronos input and output (verified in upstream model/kronos.py).
FEATURE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "amount")
CLOSE_INDEX = FEATURE_COLUMNS.index("close")
MAX_CONTEXT = 512  # upstream README, for Kronos-small and Kronos-base


@dataclass(frozen=True)
class ModelSpec:
    """One Hugging Face repository. ``revision=None`` means: resolve and record at download."""

    key: str
    repo_id: str
    revision: str | None

    @property
    def local_dir(self) -> Path:
        return MODELS_DIR / self.repo_id.split("/")[-1]


# Revisions of small + tokenizer are the ones pinned by upstream's own regression
# test. Upstream pins nothing for base, so it is resolved and written to the
# manifest at download time.
TOKENIZER = ModelSpec(
    "tokenizer", "NeoQuasar/Kronos-Tokenizer-base", "0e0117387f39004a9016484a186a908917e22426"
)
MODELS: dict[str, ModelSpec] = {
    "small": ModelSpec("small", "NeoQuasar/Kronos-small", "901c26c1332695a2a8f243eb2f37243a37bea320"),
    "base": ModelSpec("base", "NeoQuasar/Kronos-base", None),
}


@dataclass(frozen=True)
class SamplingConfig:
    """Sampling knobs that really exist upstream; defaults = KronosPredictor.predict defaults."""

    temperature: float = 1.0
    top_k: int = 0
    top_p: float = 0.9

# --- P1..P5 ------------------------------------------------------------------
DB_PATH = Path(os.environ.get("KQL_DB_PATH", ARTIFACTS_DIR / "kql.sqlite3"))
FORECAST_CACHE_DIR = ARTIFACTS_DIR / "forecast_cache"
INTERVAL = "1d"
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT",)  # test fixture, not a universe decision
SYNTHETIC_SYMBOL = "SYNTH-DEMO"  # generated random walk; never real market data
TRADING_DAYS_PER_YEAR = 365  # crypto trades every day
