# وضعیت پیاده‌سازی — چه انجام شده و چه نشده

آخرین به‌روزرسانی: **2026-11-12** · شاخه: `arena/fa97d41b-kronosquantlab` · کامیت کد: `08e87b2`

انطباق خط‌به‌خط با تنظیمات درخواستی (هر پارامتر، محل پیاده‌سازی و باقی‌مانده): [`REQUIREMENTS.md`](REQUIREMENTS.md).

این فایل تنها مرجع «وضعیت» است: چه چیزی با کد و تست پیاده شده، چه چیزی آماده ولی **با داده واقعی
اجرا نشده**، و چه چیزی عمداً انجام نشده است. اعداد و ادعاها فقط تا حدی معتبرند که در همین فایل
شاهد دارند.

## راهنمای نشانه‌ها

| نشانه | معنا |
|---|---|
| ✅ | کد نوشته و با تست خودکار پوشش داده شده است (تست‌ها آفلاین‌اند) |
| 🟡 | کد آماده است ولی اجرای واقعی/تأیید بیرونی انجام نشده (اینترنت، وزن مدل، سیستم کاربر) |
| ⛔ | عمداً پیاده‌سازی نشده؛ خارج از دامنه پژوهشی پروژه |
| ⬜ | هنوز شروع نشده |

> **قاعده ثابت پروژه:** هیچ اتصال معاملاتی، حساب صرافی، کلید API یا کد ارسال سفارش وجود ندارد.
> «اتصال» در این پروژه یعنی خواندن کندل عمومی یا خواندن فایل خروجی؛ نه بیشتر.

---

## ۱. خلاصه اجرایی

- خط لوله پژوهشی **کامل و تست‌شده** است: داده → اعتبارسنجی → SQLite → پیش‌بینی → کالیبراسیون →
  رژیم/قاعده → بک‌تست تک‌دارایی و پرتفوی → شبیه‌ساز فرضی → داشبورد/CLI.
- سه منبع داده داریم: **Binance** (عمومی)، **Nobitex** (عمومی، بدون توکن)، **Alpari** (فقط خروجی CSV از MT5).
- **هیچ عدد بازار واقعی تولید نشده است.** دلیل: sandbox توسعه به Binance/Nobitex/Hugging Face دسترسی
  ندارد و وزن‌های Kronos نیز دانلود نشده‌اند. همه اجراها با داده ساختگی و مدل پایه داخلی انجام شده‌اند.
- P0 (مقایسه Kronos-small و Kronos-base) هنوز **اجرا نشده**؛ تا آن زمان معلوم نیست Kronos از روش
  ساده بهتر است یا نه.
- وضعیت تست: **۱۸۶ passed، ۱۰ skipped** (۱۹۶ تست جمع‌آوری‌شده)؛ `ruff --select F,E9` و `mypy` پاک.

---

## ۲. ماتریس مرحله‌به‌مرحله

| بخش | کد | اجرای واقعی | توضیح کوتاه |
|---|---|---|---|
| P0.1 گزارش محیط | ✅ | 🟡 | sandbox اندازه‌گیری شده؛ سیستم هدف کاربر هنوز تأیید نشده |
| P0.2 شناسه و مجوز مدل | ✅ | 🟡 | شناسه‌ها/context/پارامترها ثبت شده؛ **مجوز وزن‌ها بررسی نشده**، وزن دانلود نشده |
| P0.3 داده Binance + اعتبارسنجی | ✅ | 🟡 | آداپتور، جایگزینی دامنه و اعتبارسنجی تست شده؛ دریافت زنده در sandbox ممکن نشد |
| P0.4–P0.6 benchmark/evaluate/report | ✅ کد | 🟡 | بدون وزن و torch اجرا نشده؛ گزارش فعلی «اجرا نشده» است |
| P1 ذخیره‌سازی و به‌روزرسانی | ✅ | 🟡 | SQLite، audit، چند بازه، مهاجرت افزودنی؛ با داده ساختگی |
| P2 پیش‌بینی، کش، کالیبراسیون بازه | ✅ | 🟡 | baseline واقعی؛ آداپتور Kronos فقط با مدل تصادفی کوچک (در این محیط skip) |
| P3 رژیم، قواعد، کالیبراسیون آستانه | ✅ | 🟡 | روش ARI/جایگشت/بوت‌استرپ تست شده؛ با داده واقعی کالیبره نشده |
| P4 بک‌تست و پرتفوی Qlib-style | ✅ | 🟡 | با داده ساختگی؛ خروجی‌های واقعی ندارد |
| P5 شبیه‌ساز paper | ✅ | 🟡 | سفارش فرضی در SQLite؛ با داده ساختگی |
| P5 داشبورد Streamlit | ✅ کد | 🟡 | ۱۰ تب؛ در sandbox اجرا نشده (streamlit نصب نیست) |
| داده Binance | ✅ | 🟡 | دو دامنه + fallback؛ درخواست زنده از این محیط مسدود |
| داده Nobitex | ✅ | 🟡 | OHLC عمومی بدون توکن؛ تست با fetcher جعلی؛ TLS محیط اجازه نداد |
| داده Alpari | ✅ CSV | ⛔ اتصال زنده | API عمومی ندارد؛ MT5 ورود می‌خواهد و در دامنه پروژه نیست |
| تست و مستندات | ✅ | — | ۱۹۶ تست، README/ARCHITECTURE/DECISIONS/CHANGELOG |
| CI (GitHub Actions) | ⬜ | — | هیچ workflow در مخزن نیست؛ تست‌ها فقط محلی اجرا می‌شوند |
| پوشش تست (coverage) | ⬜ | — | ابزار/آستانه‌ای تعریف نشده |
| بسته‌بندی/نصب به‌عنوان کتابخانه | ⬜ | — | اجرا از ریشه مخزن با اسکریپت‌های `scripts/` است |

---

## ۳. انجام‌شده (با شاهد)

### ۳.۱ لایه داده و venue

- `app/core/venues.py` — فضای نام `VENUE:SYMBOL` (بدون پیشوند = Binance)، تقویم `24/7` و `fx`،
  سالانه‌سازی ۳۶۵ یا ۲۵۲ روز، ساخت timestamp افق سشن.
- `app/data/binance.py` + `app/data/http.py` — دریافت kline عمومی، دامنه اصلی
  `data-api.binance.vision` و جایگزین خودکار `api.binance.com` در 451/403، بازگشت از ابتدا تا
  ردیف دو دامنه قاطی نشود.
- `app/data/nobitex.py` — `GET /market/udf/history` بدون توکن؛ resolutionهای `60/240/D` برای
  1h/4h/1d؛ پنجره‌های ۵۰۰ کندلی از جدید به قدیم (بدون تکیه بر معنای پارامتر `page`)؛ مدیریت صریح
  `no_data`/`error`؛ retry محدود برای 429/5xx؛ `amount = volume × close` به‌عنوان مقدار مشتق‌شده.
- `app/data/alpari.py` — خواندن خروجی CSV متاتریدر ۵: جداکننده tab/`;`/`,`، هدر `<DATE>/<TIME>` یا
  `Date/Time`، تاریخ روز-اول، `TICKVOL`، تبدیل صریح `--tz-offset`، بررسی تطابق تایم‌فریم با داده.
- `app/data/validation.py` + `app/data/engine.py` — اعتبارسنجی محافظه‌کارانه، حذف کندل ناقص/تکراری،
  گزارش `fatal_problems`/`warnings`، سیاست سخت‌گیر فقط برای venueهای ۲۴/۷ روی شبکه UTC،
  ذخیره‌نشدن داده نامعتبر و تغییرنکردن کندل ذخیره‌شده.
- `app/storage/db.py` — طرح SQLite، audit log فقط‌افزودنی، مهاجرت افزودنی `forecast_runs`
  (`interval`، `temperature`، `top_p`، `top_k`).

### ۳.۲ مدل و پیش‌بینی

- `app/forecast/base.py` — قرارداد `Forecaster`، ساخت پنجره بدون نشت، تقویم‌آگاه
  (`calendar="fx"` چندبرابر گام را می‌پذیرد و افق را روی کندل سشن می‌سازد).
- `app/forecast/baselines.py` — مدل پایه bootstrap (بدون وزن، همیشه در دسترس).
- `app/forecast/kronos_adapter.py` — بارگذاری Kronos-small/base از پوشه محلی، device، `sample_count`،
  `temperature`، `top_p`، `top_k`، سقف context.
- `app/forecast/registry.py` + `service.py` — کش پیش‌بینی (کلید شامل تنظیمات نمونه‌گیری)، ذخیره
  P10/P50/P90 و متادیتای اجرا.
- `app/evaluation/` — rolling-origin، معیارهای دقت، کالیبراسیون split-conformal، گزارش Markdown.

### ۳.۳ سیگنال، بک‌تست و پرتفوی

- `app/signals/regime.py` — رژیم روند × نوسان به‌صورت برداری و علّی (بدون look-ahead).
- `app/signals/rules.py` + `pipeline.py` — BUY/SELL/ABSTAIN و کسر هدف؛ تنها نقطه برش تاریخچه.
- `app/signals/validation.py` — کالیبراسیون آستانه با ARI بین رژیم فعلی و آینده، توزیع صفر جایگشتی،
  پایداری با بوت‌استرپ بلوکی، `validation_alpha`/`null_ari_max`/`stability_threshold` خودکار.
- `app/backtest/engine.py` + `execution.py` — بک‌تست تک‌دارایی، اجرا در open کندل بعد، کارمزد/اسلیپیج،
  معیارهای سالانه‌شده بر اساس تقویم venue.
- `app/backtest/portfolio.py` — شبیه‌ساز Qlib-style: `n_symbol_hold/drop`، `hold_thresh`،
  `time_range`، `account`، هم‌وزن، بنچمارک هم‌وزن کیهان، پرهیز از سبد چند-venue.
- `app/paper/simulator.py` — حساب فرضی، سفارش PENDING و fill در کندل بعد، ثبت در audit.

### ۳.۴ رابط‌ها و ابزار

- `scripts/kql.py` — `settings`، `data` (`update`/`demo`/`import`/`venues`/`status`)، `models`،
  `forecast`، `calibrate`، `validate`، `backtest`، `portfolio`، `paper`، `ui`.
- `scripts/p0.py` — `data`، `models`، `models --download`، `benchmark`، `evaluate`، `report`.
- `app/ui/dashboard.py` — ۱۰ تب فارسی RTL: وضعیت، داده، پیش‌بینی، کالیبراسیون، اعتبارسنجی آستانه،
  بک‌تست، پرتفوی، Paper، تنظیمات، گزارش‌های P0.
- `.env.example` — همه متغیرهای غیرمحرم؛ `settings` مقدار مؤثر را نشان می‌دهد.

### ۳.۵ مستندات

- `README.md` — نصب، تنظیمات، دستورها، تفاوت Binance/Nobitex/Alpari، قواعد زمانی.
- `docs/ARCHITECTURE.md` — نقشه ماژول‌ها، جریان داده، قراردادها و محدودیت‌ها.
- `docs/DECISIONS.md` — ۴۱ تصمیم ثبت‌شده (D1–D41) با دلیل و وضعیت.
- `docs/P0_plan.md`، `docs/P0_environment_report.md`، `docs/P0_model_benchmark.md` — وضعیت P0.
- `CHANGELOG.md` — تاریخچه تغییرات، شامل افزودن intervalها، صرافی‌ها و کالیبراسیون آستانه‌ها.

---

## ۴. انجام‌نشده یا تأییدنشده

| # | مورد | وضعیت | چرا | قدم بعدی |
|---|---|---|---|---|
| N1 | دانلود وزن‌های Kronos-small/base | 🟡 | `vendor/Kronos` وجود ندارد و Hugging Face از sandbox مسدود است | `p0.py models --download --yes` روی سیستم کاربر |
| N2 | بررسی مجوز وزن‌ها | ⬜ | model cardها قابل خواندن نبودند؛ MIT مخزن کد شامل وزن‌ها نیست | پیش از استفاده، مجوز هر model card ثبت شود |
| N3 | benchmark واقعی small/base | 🟡 | نیاز به N1 + torch + داده واقعی | `p0.py data`، `benchmark`، `evaluate`، `report` |
| N4 | اجرای خط لوله با داده واقعی بازار | 🟡 | Binance/Nobitex از این محیط در دسترس نیستند؛ هیچ عدد واقعی تولید نشده | روی سیستم کاربر `data update` و سپس `validate`/`backtest` |
| N5 | تأیید زنده نوبیتکس | 🟡 | فقط با fetcher جعلی تست شده؛ TLS محیط بسته است؛ نرخ محدودیت واقعی اندازه‌گیری نشده | `data update --symbols NOBITEX:BTCIRT` و ثبت نتیجه |
| N6 | اتصال زنده/خودکار آلپاری | ⛔ عمدی | API عمومی کندل ندارد و MT5 ورود به حساب می‌خواهد؛ پروژه حساب/کلید/سفارش ندارد | فقط خروجی CSV؛ اگر «اتصال زنده» لازم است، خارج از دامنه این پروژه است |
| N7 | دقت منطقه زمانی و تقویم تعطیلات FX | 🟡 | زمان سرور بروکر با `--tz-offset` دستی تبدیل می‌شود؛ تقویم تعطیلات مدل نشده | مقدار درست offset بروکر را در import ثبت کنید؛ تعطیلات به‌صورت هشدار دیده می‌شوند |
| N8 | اجرای داشبورد Streamlit | 🟡 | streamlit در sandbox نصب نیست؛ فقط import/compile شده | `streamlit run app/ui/dashboard.py` روی سیستم کاربر |
| N9 | CI و پوشش تست | ⬜ | هیچ workflow/آستانه coverage وجود ندارد | افزودن GitHub Actions برای `pytest` و `ruff`/`mypy` |
| N10 | بسته‌بندی به‌عنوان کتابخانه | ⬜ | اجرا از ریشه مخزن است | در صورت نیاز، `pyproject` با entry pointها |
| N11 | پرتفوی چند-venue | ⛔ عمدی | تقویم/سالانه‌سازی مشترک تعریف‌شده نیست | در صورت نیاز، طراحی تقویم ترکیبی و هم‌ترازسازی صریح |
| N12 | بازه‌های زیر ۱ ساعت (1m/5m) | ⬜ | قرارداد فعلی 1h/4h/1d است | افزودن بازه + سیاست گپ/حجم داده |
| N13 | معامله واقعی، اهرم، فروش استقراضی، سفارش | ⛔ عمدی | پروژه پژوهشی است | انجام نخواهد شد |
| N14 | paper چندنمادی | ⬜ | شبیه‌ساز paper تک‌دارایی است؛ مسیر چندنمادی، پرتفوی backtest است | طراحی حساب مشترک و تخصیص وزن |
| N15 | تأیید محیط سیستم هدف (ویندوز) | 🟡 | گزارش محیط فعلی مربوط به sandbox است | اجرای `py scripts\p0_env_probe.py` روی لپ‌تاپ |

---

## ۵. شواهد تست

`python -m pytest -q` → **۱۸۶ passed، ۱۰ skipped** (۱۹۶ جمع‌آوری‌شده). ۱۰ تست skip
وابسته به torch/وزن‌های واقعی/شبکه‌اند.

| فایل | تعداد | پوشش موضوعی |
|---|---|---|
| `tests/test_regressions.py` | ۴۶ | look-ahead، قراردادها، موارد مرزی |
| `tests/test_settings.py` | ۱۹ | تنظیمات env، بازه‌ها، کالیبراسیون میان‌بازه‌ای |
| `tests/test_research.py` | ۱۷ | مسیر پژوهشی و قواعد |
| `tests/test_kql_cli.py` | ۱۳ | قرارداد CLI و خطاها |
| `tests/test_evaluation.py` | ۱۳ | rolling/کالیبراسیون/گزارش |
| `tests/test_data.py` | ۱۲ | Binance، اعتبارسنجی، خطاهای شبکه |
| `tests/test_portfolio.py` | ۱۱ | انتخاب، fill، time_range، failover |
| `tests/test_validation.py` | ۱۰ | ARI، جایگشت، بوت‌استرپ، آستانه خودکار |
| `tests/test_kronos_adapter.py` | ۱۰ | آداپتور با مدل تصادفی کوچک (بیشتر skip در این محیط) |
| `tests/test_engine_storage.py` | ۹ | SQLite، مهاجرت، immutability |
| `tests/test_nobitex.py` | ۸ | URL/پنجره/خطا/retry/ذخیره timestamp بومی |
| `tests/test_alpari.py` | ۸ | پارس CSV، تایم‌فریم، تقویم FX و افق سشن |
| `tests/test_cli.py` | ۸ | CLI پایه |
| `tests/test_venues.py` | ۷ | فضای نام، تقویم، سالانه‌سازی، مسیردهی provider |
| `tests/test_metrics.py` | ۵ | معیارهای عددی |

کیفیت کد: `ruff check app scripts tests --select F,E9` و
`mypy app scripts/kql.py scripts/p0.py --ignore-missing-imports` هر دو پاک‌اند؛ `compileall` هم
بدون خطاست.

---

## ۶. محدودیت‌های شناخته‌شده (خارج از «بدهی فنی»)

- **بدون look-ahead** تست شده، ولی «بدون look-ahead» یعنی «درست پیاده‌شده»، نه «سودآور».
- کالیبراسیون آستانه P3 فقط precondition است؛ عبور از آن سودآوری را اثبات نمی‌کند.
- پرتفوی با تقاطع تقویم نمادها کار می‌کند؛ نماد با تاریخچه کوتاه‌تر، بازه را کوتاه می‌کند.
- داده نوبیتکس timestamp بومی (وقت ایران) دارد و بازچینی نمی‌شود؛ گپ/خارج‌ازشبکه هشدار است.
- `amount` در نوبیتکس مشتق (`volume × close`) و در MT5 مشتق (`volume × close`) است؛ گردش مالی
  گزارش‌شده صرافی نیست.
- fill با اسلیپیج ثابت و بدون عمق بازار مدل می‌شود.
- بک‌تست/پرتفوی تاریخی‌اند؛ تضمین آینده نیستند.

---

## ۷. برای بستن شکاف‌ها (روی سیستم کاربر)

```powershell
# 1) محیط و تست‌ها
py scripts\p0_env_probe.py
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-p0.txt -r requirements-ui.txt
.\.venv\Scripts\python -m pytest -q

# 2) P0 واقعی (وزن‌ها + داده Binance)
git clone https://github.com/shiyu-coder/Kronos.git vendor\Kronos
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
.\.venv\Scripts\python scripts\p0.py models --download --yes
.\.venv\Scripts\python scripts\p0.py data
.\.venv\Scripts\python scripts\p0.py benchmark
.\.venv\Scripts\python scripts\p0.py evaluate
.\.venv\Scripts\python scripts\p0.py report

# 3) مسیر کامل با داده واقعی
.\.venv\Scripts\python scripts\kql.py data update --symbols BTCUSDT ETHUSDT --interval 1d
.\.venv\Scripts\python scripts\kql.py validate --symbol BTCUSDT
.\.venv\Scripts\python scripts\kql.py portfolio --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT `
    --n-symbol-hold 3 --n-symbol-drop 1 --hold-thresh 5 --time-range 2024-01-01 2025-12-31

# 4) نوبیتکس (عمومی، بدون توکن)
.\.venv\Scripts\python scripts\kql.py data update --symbols NOBITEX:BTCIRT --interval 1d

# 5) آلپاری: خروجی MT5 را بگیرید و با offset درست import کنید
.\.venv\Scripts\python scripts\kql.py data import --symbol ALPARI:EURUSD `
    --csv .\EURUSD_1d.csv --interval 1d --format mt5 --tz-offset 3

# 6) داشبورد
.\.venv\Scripts\streamlit run app\ui\dashboard.py
```

---

## ۸. تاریخچه به‌روزرسانی این سند

| تاریخ | تغییر |
|---|---|
| 2026-11-12 | ایجاد سند؛ به‌روزرسانی پس از افزودن Nobitex/Alpari و رسیدن تست‌ها به ۱۸۶ |
| 2026-11-12 | افزودن جدول انطباق خواسته‌ها در [`REQUIREMENTS.md`](REQUIREMENTS.md) و ارجاع متقابل |
