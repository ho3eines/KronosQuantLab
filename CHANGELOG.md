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
