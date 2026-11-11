# Changelog

## بازبینی و رفع خطا — 2026-11-11

بازبینی کامل کد P0 تا P5 (pytest، ruff، mypy، fuzz توابع مالی، آزمون جهشی، اجرای CLI با ورودی نادرست،
کنسول cp1252 و مسیر فارسی). برای هر مورد یک آزمون در `tests/test_regressions.py` افزوده شد.

### خطاهای اثرگذار بر نتیجه
- بک‌تست ضریب کالیبراسیونی را به کار می‌برد که روی همان بازهٔ بک‌تست برازش شده بود (نشت آینده). → D26
- نوسان صفر، تصمیم BUY را به هدف ۰ (خروج کامل) تبدیل می‌کرد. → D27
- مسیر `data import` و `data demo` کندل بازِ امروز را ذخیره می‌کرد.
- `rebalance` به‌خاطر گردکردن اعشاری، نقد یا مقدار منفی بسیار کوچک باقی می‌گذاشت.
- بازار تخت «نزولی» تشخیص داده می‌شد.
- بک‌تستی که همهٔ پیش‌بینی‌هایش شکست خورده بود با کد ۰ تمام می‌شد.

### خرابی‌ها (traceback به‌جای پیام روشن)
- `UnicodeEncodeError` در کنسول cp1252 ویندوز هنگام چاپ مسیر غیرلاتین.
- `--n-paths 1`، `--level 1.0`، `paper init --cash nan`، فایل CSV ناموجود یا خالی.
- فایل cache ناقص یا خراب؛ ردیف نادرست از Binance؛ timestamp دارای منطقهٔ زمانی در adapter مدل.

### اعتبارسنجی و خروجی
- مقادیر صفر یا منفی برای `--rebalance-every`، `--n-decisions`، `--horizon`، `--fee-bps`، `--cash`، `--calib-fraction` اکنون رد می‌شوند.
- JSON: دیگر `NaN` خام یا عدد numpy به‌شکل رشته نوشته نمی‌شود. → D28
- `paper step` اگر تازه‌ترین کندل بیش از یک روز کهنه باشد هشدار می‌دهد.
- آزمون «اجرا در باز کندل بعد» قبلاً نمی‌توانست خطا را بگیرد (در fixture، open با close قبلی برابر بود)؛ آزمون با شکاف قیمتی افزوده شد.
- ۵ خطای mypy و importهای بی‌استفاده رفع شد.

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
