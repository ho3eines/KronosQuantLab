# Changelog

## تنظیمات داده، مدل و کالیبراسیون آستانه‌ها — 2026-11-11

پیاده‌سازی کامل سطح تنظیمات توصیف‌شده (دامنه‌های Binance، شناسه مدل، آستانه‌های P3،
نمونه‌گیری، پرتفوی و پنجره/بازه). همه با داده ساختگی و مدل پایه آزمایش شده‌اند؛ هیچ‌کدام روی
داده یا وزن واقعی اجرا نشده است.

### داده و بازار
- دو دامنه Binance: `data-api.binance.vision` و جایگزین `api.binance.com`؛ خطای **451/403**
  خودکار به دامنه بعدی می‌رود، دریافت از ابتدا تکرار می‌شود (بدون مخلوط‌شدن ردیف‌ها) و دامنه
  سالم تا پایان پردازه به خاطر سپرده می‌شود. خطاهای دیگر (مثل 500) بی‌صدا دوباره تلاش نمی‌شوند.
- بازه‌های `1h`، `4h` و `1d` با ذخیره جداگانه در SQLite، تشخیص شکاف بر اساس طول کندل و
  سالانه‌سازی نوسان/شارپ بر اساس تعداد کندل در سال.
- ستون‌های `forecast_runs.interval`، `temperature`، `top_p` و `top_k` با مهاجرت افزودنی
  (پایگاه‌های قبلی حفظ می‌شوند) تا هر پیش‌بینی با تنظیمات نمونه‌گیری‌اش بازتولیدپذیر باشد.
- `data status` تعداد کندل‌های گمشده را بر حسب **کندل** (`missing_bars`) و برای بازه‌های
  درون‌روزی زمان شروع/پایان را با ساعت گزارش می‌کند.

### مدل
- `model_id` و `tokenizer_id` هر مدل در `config` و خروجی `kql.py models` / `p0.py models`.
- نمایش پارامترها (24.7M / 102.3M) و طول زمینه 512.
- `sample_count`، `temperature`، `top_p` و `top_k` به‌صورت پرچم CLI و کلید cache.

### P3
- `app/signals/validation.py`: کالیبراسیون آستانه‌ها با ARI بین رژیم فعلی و رژیم آینده،
  توزیع صفر از `n_permutations` جایگشت، پایداری با `n_bootstrap` بوت‌استرپ بلوکی،
  `validation_alpha`، `validation_null_ari_max` و `validation_stability_threshold` خودکار.
- برچسب‌گذاری رژیم برداری شد (`regime_series`) و همان تابع، `detect_regime` را می‌سازد.

### P4
- `app/backtest/portfolio.py`: شبیه‌ساز سبد Qlib-style با `n_symbol_hold`، `n_symbol_drop`،
  `hold_thresh`، `time_range` (معادل `--time-range START END` یا `--start/--end`)، `account`،
  اجرا در باز کندل بعد، کارمزد/اسلیپیج، نقد غیرمنفی،
  بدون اهرم و بدون فروش استقراضی.
- `kql.py portfolio` و ذخیره `portfolio.json`/`equity.csv`/`trades.csv`.
- سقف `lookback=512` و `MAX_HORIZON=96` در لایه مدل و CLI اعمال می‌شود.

### ابزار
- `kql.py settings` برای دیدن تنظیمات مؤثر؛ `data status` با بازه؛ داشبورد با انتخاب بازه،
  تب اعتبارسنجی و تب پرتفوی.

### تست
- `tests/test_settings.py`، `tests/test_validation.py`، `tests/test_portfolio.py` و آزمون‌های
  CLI برای `settings`، `validate`، `portfolio`، بازه ۱ ساعته و سقف‌های جدید.

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
