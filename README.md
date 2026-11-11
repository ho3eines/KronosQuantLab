# Kronos Quant Lab

سامانه محلی پژوهشی برای داده روزانه رمزارز: دریافت و اعتبارسنجی داده، پیش‌بینی احتمالاتی با Kronos-small و Kronos-base، کالیبراسیون بازه‌ها، پژوهش قواعد تصمیم، بک‌تست و شبیه‌ساز معامله فرضی با داشبورد.

> **فقط پژوهش و شبیه‌سازی محلی.** این پروژه به هیچ صرافی یا حسابی وصل نمی‌شود، کلید API نمی‌گیرد و هیچ کدی برای ارسال سفارش ندارد. «سفارش»ها ردیف‌هایی در یک فایل SQLite محلی‌اند. هیچ خروجی‌ای توصیه مالی نیست؛ پیش‌بینی قطعیت نیست و نتیجه بک‌تست تضمین سود نیست.

## وضعیت واقعی

| مرحله | کد و تست | اجرا با داده و مدل واقعی |
|---|---|---|
| P0 مقایسه small و base | نوشته و تست شده | **اجرا نشده** |
| P1 موتور داده (SQLite) | نوشته و تست شده | اتصال به Binance اجرا نشده |
| P2 پیش‌بینی و کالیبراسیون | نوشته و تست شده | اجرا نشده |
| P3 رژیم بازار و قواعد تصمیم | نوشته و تست شده | آستانه‌ها اعتبارسنجی نشده‌اند |
| P4 بک‌تست | نوشته و تست شده | اجرا نشده |
| P5 شبیه‌ساز و داشبورد | نوشته و تست شده | اجرا نشده |

محیط توسعه به Hugging Face و Binance دسترسی نداشت. همه چیز با داده **ساختگی**، مدل پایه داخلی و کد واقعی Kronos با وزن تصادفی آزمایش شده است. تا وقتی P0 روی سیستم شما اجرا نشود، معلوم نیست Kronos از روش ساده بهتر است یا نه؛ P3 تا P5 ابزار پژوهش‌اند، نه استراتژی تأییدشده.

## پیش‌نیاز

- Windows 64-bit، ‏Python **3.11 یا 3.12**، Git
- حدود 2 GB فضای آزاد برای وزن‌ها و محیط مجازی (تخمین)
- اینترنت فقط برای نصب، دانلود وزن و دریافت داده

## نصب (PowerShell، از ریشه مخزن)

```powershell
py scripts\p0_env_probe.py                       # شناسایی محیط؛ چیزی نصب نمی‌کند
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-p0.txt -r requirements-ui.txt
git clone https://github.com/shiyu-coder/Kronos.git vendor\Kronos
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
.\.venv\Scripts\python -m pytest -q               # بدون اینترنت و بدون وزن مدل
```

## گام اول: P0 (پیش از هر چیز دیگر)

```powershell
.\.venv\Scripts\python scripts\p0.py models                    # مجوز، حجم، فضای دیسک؛ دانلود نمی‌کند
.\.venv\Scripts\python scripts\p0.py models --download --yes
.\.venv\Scripts\python scripts\p0.py data
.\.venv\Scripts\python scripts\p0.py benchmark --smoke         # ۱ مسیر، افق ۷
.\.venv\Scripts\python scripts\p0.py benchmark                 # ۱ ← ۵ ← ۲۰ مسیر
.\.venv\Scripts\python scripts\p0.py evaluate                  # دقت در برابر naive
.\.venv\Scripts\python scripts\p0.py report                    # docs\P0_model_benchmark.md
```

## کار روزمره (P1 تا P5)

مدل‌ها: `baseline-bootstrap` (داخلی، بدون وزن)، `kronos-small`، `kronos-base`.

```powershell
$k = ".\.venv\Scripts\python", "scripts\kql.py"
& $k[0] $k[1] data update --symbols BTCUSDT ETHUSDT     # P1: کندل‌های جدید به SQLite
& $k[0] $k[1] data status
& $k[0] $k[1] models
& $k[0] $k[1] forecast  --symbol BTCUSDT --model kronos-small        # P2: P10/P50/P90
& $k[0] $k[1] calibrate --symbol BTCUSDT --model kronos-small        # P2: پوشش واقعی و ضریب کالیبراسیون
& $k[0] $k[1] backtest  --symbol BTCUSDT --model kronos-small        # P4
& $k[0] $k[1] paper init                                             # P5: حساب فرضی
& $k[0] $k[1] paper step --symbol BTCUSDT --model kronos-small       # روزی یک بار
& $k[0] $k[1] paper status
.\.venv\Scripts\streamlit run app\ui\dashboard.py                    # داشبورد
```

بدون اینترنت و بدون وزن هم می‌شود همه مسیر را امتحان کرد: `data demo` یک سری ساختگی با نماد `SYNTH-DEMO` می‌سازد و `baseline-bootstrap` نیازی به وزن ندارد. اعداد این حالت هیچ معنایی برای بازار واقعی ندارند.

هر اجرای `benchmark`، `evaluate`، `calibrate` و `backtest` پوشه تازه‌ای در `artifacts\reports\` می‌سازد و چیزی را بازنویسی نمی‌کند.

## قواعد زمانی (کنترل look-ahead)

- تصمیم پس از بسته‌شدن کندل t و فقط با کندل‌های ۰ تا t گرفته می‌شود.
- اجرا در قیمت باز کندل t+1، با کارمزد و اسلیپیج.
- فقط خرید و نگهداری یا نقد (بدون فروش استقراضی، بدون اهرم).
- کالیبراسیون روی مبدأهای قدیمی‌تر fit و روی مبدأهای جدیدتر سنجیده می‌شود.

## مستندات

| سند | محتوا |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | ماژول‌ها و جریان داده |
| [docs/DECISIONS.md](docs/DECISIONS.md) | تصمیم‌های فنی و دلیل آن‌ها |
| [docs/P0_plan.md](docs/P0_plan.md) | تحقیق منبع مدل و API واقعی Kronos |
| [docs/P0_environment_report.md](docs/P0_environment_report.md) | گزارش محیط |
| [CHANGELOG.md](CHANGELOG.md) | تغییرات |

## عیب‌یابی

| نشانه | اقدام |
|---|---|
| Kronos خیلی کند است | `--n-paths 10`، `--n-origins 8`، `--n-decisions 12`. پیش‌بینی‌ها در `artifacts\forecast_cache` ذخیره می‌شوند و اجرای دوباره همان بک‌تست سریع است. |
| خطای حافظه در P0 | `--batch-size 5` |
| `could not fetch ... binance` | شبکه به Binance دسترسی ندارد؛ `KQL_BINANCE_BASE_URL` در `.env.example` یا `data import --csv`. |
| `gap` هنگام به‌روزرسانی داده | provider کندلی را جا انداخته است؛ چیزی ذخیره نمی‌شود تا سری ناقص وارد پایگاه نشود. |
| `factor = None` در کالیبراسیون | مبدأ کافی نیست (برای سطح ۰٫۸ حداقل ۴ مبدأ کالیبراسیون)؛ `--n-origins` را زیاد کنید. |
| `weights missing` | گام P0 ‏(`p0.py models --download --yes`) اجرا نشده است. |
| `license unknown` | model card مجوزی اعلام نکرده؛ صفحه مدل را بخوانید و فقط در صورت پذیرش `--accept-unknown-license` بدهید. |
