# Changelog

## P0 — در جریان

### 2026-11-11 — شناسایی و طرح (بدون دانلود وزن، بدون نصب)
- افزوده شد: `scripts/p0_env_probe.py` (probe فقط‌خواندنی محیط).
- افزوده شد: `docs/P0_environment_report.md`، `docs/P0_plan.md`، `docs/DECISIONS.md`.
- افزوده شد: `.gitignore`، `artifacts/reports/.gitkeep`.
- بازنویسی شد: `README.md` (قبلاً فقط عنوان بود).

### 2026-11-11 — پیاده‌سازی خط لوله P0
- افزوده شد: `app/core`، `app/data`، `app/forecast`، `app/evaluation`.
- افزوده شد: `scripts/p0.py` با فرمان‌های `data`، `models`، `benchmark`، `evaluate`، `report`.
- افزوده شد: `tests/` (۴۷ تست)، `pyproject.toml`، `requirements-p0.txt`، `.env.example`، `docs/ARCHITECTURE.md`.
- اجرا نشد: دانلود وزن‌های واقعی، دریافت داده واقعی، benchmark و ارزیابی واقعی (محیط توسعه به Hugging Face و Binance دسترسی ندارد).

## P1 تا P5 — پیاده‌سازی‌شده، با داده و مدل واقعی اجرا نشده

### 2026-11-11
- P1: `app/storage/db.py`، `app/data/engine.py` (SQLite، به‌روزرسانی افزایشی، چند نماد، داده ساختگی برای آزمایش).
- P2: `app/forecast/baselines.py`، `registry.py`، `service.py`، `app/evaluation/calibration.py`.
- P3: `app/signals/regime.py`، `rules.py`، `pipeline.py`.
- P4: `app/backtest/execution.py`، `engine.py`.
- P5: `app/paper/simulator.py`، `app/ui/dashboard.py`، `requirements-ui.txt`.
- `app/services.py` و `scripts/kql.py`.
- تست‌ها: `tests/test_engine_storage.py`، `tests/test_research.py`، `tests/test_kql_cli.py`.
- تغییر: Python پشتیبانی‌شده 3.11 تا 3.12.
