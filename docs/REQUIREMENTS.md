# انطباق با تنظیمات درخواستی — انجام‌شده / انجام‌نشده

آخرین به‌روزرسانی: **2026-11-12** · کامیت کد: `07415e3` · اسناد تکمیلی: [`STATUS.md`](STATUS.md)، [`AUDIT.md`](AUDIT.md)

این فایل همان «داکیومنت تنظیمات» را خط‌به‌خط بررسی می‌کند: هر خواسته، محل پیاده‌سازی، شاهد تست و
چیزی که هنوز باقی مانده است. جدول مرحله‌به‌مرحله (P0–P5) در [`STATUS.md`](STATUS.md) است؛ اینجا
نگاه از سمت **خواسته‌های شما** است.

**جمع‌بندی: ۲۷ مورد بررسی شد — ۲۲ مورد کامل ✅، ۵ مورد نیمه‌تمام 🟡 (کد آماده، اجرای واقعی یا
وزن مدل باقی مانده)، و یک جزء عمداً انجام‌نشده ⛔ (اتصال زنده آلپاری).**

---

## ۱. داده

| # | خواسته | وضعیت | محل پیاده‌سازی | شاهد | باقی‌مانده |
|---|---|---|---|---|---|
| R1 | دامنه اصلی `https://data-api.binance.vision` | ✅ | `app/core/config.py` (`BINANCE_PRIMARY_URL`) | `kql.py settings` همین مقدار را نشان می‌دهد؛ `tests/test_data.py` | — |
| R2 | دامنه جایگزین `https://api.binance.com` به‌صورت خودکار روی HTTP 451 | ✅ | `app/data/binance.py` (`endpoint_candidates`, `fetch_klines`); 403 هم پوشش داده شده | تست‌های failover در `tests/test_data.py` و `tests/test_settings.py` | — |
| R3 | داده عمومی و بدون کلید | ✅ | هیچ هدر احراز هویتی وجود ندارد؛ `data venues` ستون `public_api` و توضیح هر venue را نشان می‌دهد | تست «بدون اتصال معاملاتی» در `tests/test_research.py` کد را برای کتابخانه صرافی/endpoint سفارش/کلید API می‌گردد | — |
| R4 | اتصال به Nobitex (درخواست بعدی) | ✅ کد / 🟡 دود واقعی | `app/data/nobitex.py` (`GET /market/udf/history`، بدون توکن) | `tests/test_nobitex.py` (۸ تست با fetcher جعلی) | درخواست زنده از این محیط TLS نمی‌گیرد؛ روی سیستم کاربر یک بار اجرا شود |
| R5 | اتصال به Alpari | ✅ فقط CSV / ⛔ اتصال زنده | `app/data/alpari.py` + `data import --format mt5` | `tests/test_alpari.py` (۱۳ تست، شامل خروجی UTF-16 متاتریدر) | آلپاری API عمومی کندل ندارد و MT5 ورود می‌خواهد؛ اتصال زنده عمداً در دامنه پروژه نیست |

---

## ۲. مدل‌ها

| # | خواسته | وضعیت | محل پیاده‌سازی | شاهد | باقی‌مانده |
|---|---|---|---|---|---|
| R6 | `NeoQuasar/Kronos-small` (~24.7M) | ✅ شناسه / 🟡 وزن | `config.MODELS["small"]` با `repo_id`، `parameters="24.7M"`، `context_length=512` | `kql.py models` و `settings`؛ `p0.py models` | دانلود وزن + بررسی مجوز model card (N1/N2) |
| R7 | `NeoQuasar/Kronos-base` (~102.3M) | ✅ شناسه / 🟡 وزن | `config.MODELS["base"]` با `parameters="102.3M"` | همان | همان |
| R8 | `NeoQuasar/Kronos-Tokenizer-base` مشترک، context 512 | ✅ | `config.TOKENIZER`، `TOKENIZER_REPO_ID`، `MAX_CONTEXT=512` | `tests/test_settings.py` سقف‌ها و شناسه‌ها را بررسی می‌کند | — |

---

## ۳. کالیبراسیون آستانه P3 «با داده واقعی»

| # | خواسته | وضعیت | محل پیاده‌سازی | شاهد | باقی‌مانده |
|---|---|---|---|---|---|
| R9 | `validation_alpha` پیش‌فرض 0.05 | ✅ | `config.VALIDATION_ALPHA`، `ValidationParams.alpha`، `--alpha` | `tests/test_validation.py` + `tests/test_settings.py` | — |
| R10 | `validation_null_ari_max` خودکار اگر `None` | ✅ | `calibrate_thresholds`؛ مقدار صریح هم پذیرفته و با پرچم `consistent` گزارش می‌شود | تست‌های آستانه خودکار و صریح | — |
| R11 | `validation_stability_threshold` خودکار اگر `None` | ✅ | همان ماژول؛ اگر از کران صفر کوچک‌تر باشد هشدار می‌دهد | همان تست‌ها | — |
| R12 | `n_permutations` پیش‌فرض 100 | ✅ | `config.N_PERMUTATIONS`، CLI `--n-permutations` | `settings` و تست‌ها | — |
| R13 | `n_bootstrap` پیش‌فرض 50 | ✅ | `config.N_BOOTSTRAP`، CLI `--n-bootstrap` | همان | — |
| R14 | کالیبراسیون روی **داده واقعی** | 🟡 | روش کامل است: ARI رژیم فعلی/آینده + توزیع صفر جایگشتی + بوت‌استرپ بلوکی | `kql.py validate` در sandbox فقط با داده ساختگی اجرا شد | روی داده ذخیره‌شده واقعی اجرا و نتیجه ثبت شود (N4) |

> عبور از این آزمون فقط می‌گوید برچسب‌های رژیم از تصادف جدا و پایدارند؛ **سودآوری را اثبات نمی‌کند**.

---

## ۴. بک‌تست و شبیه‌سازی

| # | خواسته | وضعیت | محل پیاده‌سازی | شاهد | باقی‌مانده |
|---|---|---|---|---|---|
| R15 | `sample_count` | ✅ | `--sample-count` (نام دیگر `--n-paths`)، `n_paths` در `make_forecast`، کش شامل تعداد مسیرها | `tests/test_settings.py` (کلید cache) و تست‌های CLI | — |
| R16 | `temperature` (T)، `top_p`، `top_k` | ✅ | `config.SamplingConfig`، پرچم‌های CLI، ارسال به Kronos، ثبت در `forecast_runs` | تست‌های نمونه‌گیری/کش + ستون‌های DB | با وزن واقعی Kronos اجرا نشده (N1) |
| R17 | `backtest_n_symbol_hold = 50` | ✅ | `PortfolioConfig.n_symbol_hold` پیش‌فرض 50؛ `--n-symbol-hold` / `--backtest-n-symbol-hold` | `tests/test_portfolio.py` | — |
| R18 | `backtest_n_symbol_drop = 5` | ✅ | پیش‌فرض 5؛ `--n-symbol-drop` / `--backtest-n-symbol-drop` | همان | — |
| R19 | `backtest_hold_thresh = 5` | ✅ | پیش‌فرض 5 کندل؛ `--hold-thresh` / `--backtest-hold-thresh` | همان | — |
| R20 | `backtest_time_range` | ✅ | `--time-range START END`؛ `--start/--end` هم پذیرفته می‌شود؛ هر دو با هم خطا (کد ۲) | `tests/test_kql_cli.py` و `tests/test_portfolio.py` | — |
| R21 | `account = 100_000_000` | ✅ | `PortfolioConfig.initial_cash` پیش‌فرض 100,000,000؛ `--account` | `settings` و تست config | — |

اجرای سفارش‌ها در **باز کندل بعد** با کارمزد/اسلیپیج، long-only، نقد غیرمنفی و وزن مساوی
`1/تعداد نگهداری` پیاده شده است؛ این‌ها در `tests/test_portfolio.py` و `tests/test_regressions.py`
(شامل تست دست‌کاری آینده) پوشش دارند.

---

## ۵. پنجره و بازه کندل

| # | خواسته | وضعیت | محل پیاده‌سازی | شاهد | باقی‌مانده |
|---|---|---|---|---|---|
| R22 | `lookback` پیش‌فرض 400، حداکثر 512 | ✅ | `config.LOOKBACK`، محدودیت در `make_window` و dataclassها، `--lookback` | `tests/test_settings.py` و تست‌های مرزی | — |
| R23 | `pred_len` / `MAX_HORIZON` پیش‌فرض 96 | ✅ | `config.DEFAULT_PRED_LEN`/`MAX_HORIZON`، `--horizon` با نام دیگر `--pred-len` | تست‌های سقف افق | — |
| R24 | `interval` یکی از `1h`، `4h`، `1d` | ✅ | `app/core/timeframes.py`؛ ستون `interval` در `candles` و `forecast_runs`؛ سالانه‌سازی و شکاف‌یابی بر اساس بازه | تست‌های بازه، مهاجرت، و «کالیبراسیون بازه دیگر اعمال نشود» | — |

---

## ۶. قواعد ثابت و کیفیت

| # | خواسته/تعهد | وضعیت | محل | شاهد |
|---|---|---|---|---|
| R25 | فقط پژوهش: بدون حساب، کلید، سفارش | ✅ | کل مخزن؛ `data venues` و README هم صریح | تست خودکار `tests/test_research.py` |
| R26 | تست خودکار | ✅ | `tests/` (۱۶ فایل) | **۱۹۷ passed، ۱۰ skipped** (۲۰۷ جمع‌آوری‌شده) |
| R27 | مستندات | ✅ | README، ARCHITECTURE، DECISIONS (D1–D42)، STATUS، AUDIT، CHANGELOG، P0 docs | همین فایل‌ها |

---

## ۷. شکاف‌های باقی‌مانده (به ترتیب اولویت)

| اولویت | کار | چرا مهم است | دستور/اقدام |
|---|---|---|---|
| ۱ | دانلود وزن‌های Kronos + بررسی مجوز model card | بدون آن Kronos واقعی اجرا نمی‌شود | `p0.py models --download --yes` (پس از خواندن مجوز) |
| ۲ | benchmark/evaluate واقعی small/base | تنها راه پاسخ به «آیا Kronos بهتر است؟» | `p0.py data` → `benchmark` → `evaluate` → `report` |
| ۳ | اجرای خط لوله با داده واقعی | همه اعداد فعلی ساختگی‌اند | `data update` و سپس `validate`/`backtest`/`portfolio` |
| ۴ | دود زنده نوبیتکس | فقط با fetcher جعلی تست شده | `data update --symbols NOBITEX:BTCIRT --interval 1d` |
| ۵ | اجرای داشبورد | در sandbox نصب/اجرا نشده | `streamlit run app/ui/dashboard.py` |
| ۶ | CI + coverage | الان هیچ workflow‌ای نیست | افزودن GitHub Actions برای pytest/ruff/mypy |
| ۷ | paper چندنمادی | paper فعلی تک‌دارایی است | طراحی جدا (مسیر چندنمادی: backtest پرتفوی) |

---

## ۸. تعدیل‌های آگاهانه نسبت به خواسته اولیه

| خواسته | تصمیم | دلیل |
|---|---|---|
| «اتصال به آلپاری» | فقط خروجی MT5 (CSV)، بدون اتصال زنده | آلپاری API عمومی کندل ندارد؛ MT5 ورود به حساب می‌خواهد و پروژه حساب/کلید/سفارش ندارد |
| «کالیبراسیون با داده واقعی» | روش و ابزار آماده، اجرا نشده | محیط توسعه به داده واقعی دسترسی ندارد؛ روی سیستم کاربر انجام می‌شود |
| سبد با نمادهای چند صرافی | رد می‌شود | تقویم و سالانه‌سازی مشترک تعریف‌شده‌ای ندارد (۳۶۵ روز در برابر ۲۵۲) |
| داده نوبیتکس | timestamp بومی حفظ می‌شود؛ گپ/خارج از شبکه UTC هشدار است | بازچینی داده آن را تحریف می‌کرد؛ `amount` هم صریحاً مشتق است |

---

## ۹. تاریخچه

| تاریخ | تغییر |
|---|---|
| 2026-11-12 | ایجاد این جدول انطباق و اتصال آن به `STATUS.md`؛ هیچ تغییر اجرایی نداشت |
| 2026-11-12 | بازبینی کد در برابر مستندات ([`AUDIT.md`](AUDIT.md))؛ شمار تست‌ها ۱۹۷ و R5/R26/R27 به‌روز شد |
