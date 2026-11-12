# Kronos Quant Lab

سامانه محلی پژوهشی برای داده رمزارز (۱ ساعته، ۴ ساعته یا روزانه): دریافت و اعتبارسنجی داده، پیش‌بینی احتمالاتی با Kronos-small و Kronos-base، کالیبراسیون بازه‌ها، کالیبراسیون آستانه‌های تصمیم، پژوهش قواعد تصمیم، بک‌تست تک‌دارایی و پرتفوی چندنمادی و شبیه‌ساز معامله فرضی با داشبورد.

> **فقط پژوهش و شبیه‌سازی محلی.** این پروژه به هیچ صرافی یا حسابی وصل نمی‌شود، کلید API نمی‌گیرد و هیچ کدی برای ارسال سفارش ندارد. «سفارش»ها ردیف‌هایی در یک فایل SQLite محلی‌اند. هیچ خروجی‌ای توصیه مالی نیست؛ پیش‌بینی قطعیت نیست و نتیجه بک‌تست تضمین سود نیست.

## وضعیت: چه انجام شده و چه نشده

جدول زیر خلاصه است؛ **شرح کامل با شاهد، محدودیت‌ها و قدم‌های بعدی در
[`docs/STATUS.md`](docs/STATUS.md)** آمده است.

| بخش | کد و تست | اجرای واقعی |
|---|---|---|
| P0 مقایسه Kronos-small/base | ✅ | 🟡 وزن دانلود نشده؛ benchmark اجرا نشده |
| P1 ذخیره‌سازی، بازه‌ها، اعتبارسنجی | ✅ | 🟡 با داده ساختگی |
| P1 داده Binance (دو دامنه + fallback) | ✅ | 🟡 درخواست زنده از sandbox مسدود |
| P1 داده Nobitex (عمومی، بدون توکن) | ✅ | 🟡 فقط با fetcher جعلی تست شده |
| P1 داده Alpari (CSV متاتریدر ۵) | ✅ | ⛔ اتصال زنده ندارد (عمدی)؛ فقط import |
| P2 پیش‌بینی، کش، کالیبراسیون بازه | ✅ | 🟡 بدون وزن واقعی Kronos |
| P3 رژیم، قواعد، کالیبراسیون آستانه | ✅ | 🟡 با داده ساختگی |
| P4 بک‌تست تک‌دارایی و پرتفوی | ✅ | 🟡 با داده ساختگی |
| P5 paper و داشبورد | ✅ | 🟡 داشبورد در این محیط اجرا نشده |
| تست، مستندات | ✅ | ۱۹۲ passed، ۱۰ skipped |
| CI، coverage، بسته‌بندی | ⬜ | شروع نشده |

✅ = کد + تست خودکار · 🟡 = آماده ولی اجرای واقعی/تأیید بیرونی نشده · ⛔ = عمداً خارج از دامنه ·
⬜ = شروع نشده

**هیچ عدد بازار واقعی تولید نشده است:** sandbox توسعه به Binance/Nobitex/Hugging Face دسترسی ندارد و
وزن‌های Kronos موجود نیستند. آداپتور Kronos با یک مدل تصادفی کوچک تست می‌شود و در این محیط بیشتر
تست‌های آن skip می‌شوند. تا وقتی P0 روی سیستم شما اجرا نشود، برتری Kronos نسبت به روش ساده اثبات
نشده است؛ P3 تا P5 ابزار پژوهش‌اند، نه استراتژی تأییدشده.

## پیش‌نیازها

| مورد | حداقل | توضیح |
|---|---|---|
| سیستم‌عامل | Windows 10/11 64-bit | مسیر اصلی همین است؛ Linux و macOS هم پشتیبانی می‌شوند (پایین‌تر) |
| Python | **3.11 یا 3.12** | نسخه 3.13 پشتیبانی نمی‌شود؛ pandas 2.2.2 برای آن wheel ندارد |
| Git | 2.30+ | برای clone همین مخزن و مخزن Kronos |
| PowerShell | 5.1+ | دستورهای زیر برای PowerShell نوشته شده‌اند |
| فضای دیسک | حدود ۳ GB آزاد | محیط مجازی + وزن‌ها (~0.6 GB) + داده و گزارش‌ها |
| RAM | ۸ GB پیشنهادی | CPU هم کافی است، فقط کندتر |
| GPU | اختیاری | CUDA سرعت را زیاد می‌کند، ولی لازم نیست |
| اینترنت | برای نصب/وزن/داده | اجرای آزمایشی با داده ساختگی بدون اینترنت هم ممکن است |

بررسی سریع نسخه‌ها پیش از شروع:

```powershell
py --version
git --version
```

اگر `py` شناخته نشد، Python را از [python.org](https://www.python.org/downloads/) نصب کنید و گزینه
«Add python.exe to PATH» را بزنید؛ در این حالت از `python` به‌جای `py` استفاده کنید.

## نصب گام‌به‌گام (Windows / PowerShell)

> هیچ‌کدام از این دستورها به حساب صرافی وصل نمی‌شوند و کلید API نمی‌خواهند. نصب فقط کد، کتابخانه و
> وزن مدل را روی همین دستگاه می‌گذارد.

### ۱) دریافت کد

```powershell
git clone https://github.com/ho3eines/KronosQuantLab.git
cd KronosQuantLab
```

### ۲) بررسی محیط (بدون نصب چیزی)

```powershell
py scripts\p0_env_probe.py
```

خروجی می‌گوید Python/Git/دیسک/GPU چه وضعی دارند و در `artifacts\reports\` ذخیره می‌شود.

### ۳) ساخت و فعال‌سازی محیط مجازی

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

اگر PowerShell اجازه اجرای اسکریپت نداد:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

از این به بعد `python` به محیط مجازی اشاره می‌کند. اگر نمی‌خواهید فعال کنید، همه‌جا
`.\.venv\Scripts\python` بنویسید.

### ۴) نصب وابستگی‌ها

```powershell
python -m pip install -r requirements-p0.txt -r requirements-ui.txt
```

- `requirements-p0.txt`: هسته (numpy/pandas/torch/وابستگی‌های Kronos) + pytest.
- `requirements-ui.txt`: فقط داشبورد (Streamlit/Plotly). اگر فقط CLI می‌خواهید، این یکی را نصب نکنید.
- نصب torch بزرگ است و چند دقیقه طول می‌کشد. روی ویندوز wheel پیش‌فرض PyPI نسخه CPU است. اگر کارت
  NVIDIA دارید و CUDA می‌خواهید، **قبل** از دستور بالا:
  ```powershell
  python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
  ```

### ۵) کد Kronos در commit pin‌شده

```powershell
git clone https://github.com/shiyu-coder/Kronos.git vendor\Kronos
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
```

این پوشه در `.gitignore` است و وزن‌ها داخلش نیست؛ فقط کد مدل است.

### ۶) تست نصب (بدون اینترنت و بدون وزن)

```powershell
python -m pytest -q
python scripts\kql.py settings
python scripts\kql.py models
```

انتظار: **هیچ تست `failed` نداشته باشید**. تعداد `skipped` به نصب بودن torch/Streamlit و وزن‌ها بستگی
دارد؛ روی نصب کامل، عددها بیشتر از «192 passed, 10 skipped» است. در `kql.py models`، `baseline-bootstrap` باید available باشد و
`kronos-small/base` تا زمانی که وزن دانلود نشود «NOT available» نشان می‌دهند؛ این طبیعی است و یعنی
نصب سالم است.

### ۷) تنظیمات محلی (`.env`)

```powershell
Copy-Item .env.example .env
notepad .env
```

- پروژه هنگام import، فایل `.env` ریشه مخزن را می‌خواند و فقط کلیدهای `KQL_*` را اعمال می‌کند.
- اگر همان متغیر در محیط واقعی تنظیم شده باشد، **مقدار محیط بر فایل اولویت دارد**.
- `.env` در `.gitignore` است و نباید هیچ کلید/رمزی داشته باشد (این پروژه به کلید نیاز ندارد).
- برای یک اجرای موقت بدون فایل:
  ```powershell
  $env:KQL_ARTIFACTS_DIR = "D:\kql_artifacts"
  python scripts\kql.py settings
  ```
  این متغیر فقط در همین پنجره PowerShell معتبر است. مسیر فایل دیگر: `$env:KQL_ENV_FILE = "D:\kql\.env"`.

### ۸) اولین اجرای آزمایشی (بدون اینترنت و بدون وزن مدل)

```powershell
python scripts\kql.py data demo --rows 900
python scripts\kql.py forecast --symbol SYNTH-DEMO --model baseline-bootstrap --horizon 10 --sample-count 10
python scripts\kql.py backtest --symbol SYNTH-DEMO --model baseline-bootstrap --n-paths 10 --n-decisions 3 --rebalance-every 60
python scripts\kql.py paper init
python scripts\kql.py paper step --symbol SYNTH-DEMO --model baseline-bootstrap
python scripts\kql.py paper status
```

`SYNTH-DEMO` داده **ساختگی** است؛ فقط برای اطمینان از سالم بودن نصب. اعدادش هیچ معنای بازاری ندارند.

### ۹) دانلود وزن‌های Kronos (اختیاری، لازم برای مدل واقعی)

```powershell
python scripts\p0.py models                       # مجوز/حجم/commit؛ چیزی دانلود نمی‌کند
python scripts\p0.py models --download --yes
```

- اگر model card مجوز اعلام نکرده باشد دانلود رد می‌شود؛ پس از خواندن صفحه مدل
  `--accept-unknown-license` را اضافه کنید.
- حجم تقریبی مجموع: حدود 0.6 GB، در `artifacts\models\`.
- بعد از دانلود، `python scripts\kql.py models` باید `kronos-small` و `kronos-base` را available ببیند.

### ۱۰) داده واقعی بازار

```powershell
python scripts\p0.py data                        # نمونه BTCUSDT روزانه + اعتبارسنجی
python scripts\kql.py data update --symbols BTCUSDT ETHUSDT --interval 1d
python scripts\kql.py data status --interval 1d
```

اگر دامنه‌های Binance مسدود بودند پیام روشن می‌دهد؛ جایگزین: `data import --csv` یا
`data update --symbols NOBITEX:BTCIRT` (عمومی و بدون توکن). خروجی MT5 آلپاری هم با
`data import --format mt5` وارد می‌شود.

### ۱۱) اجرای داشبورد

```powershell
python -m streamlit run app\ui\dashboard.py
```

مرورگر روی `http://localhost:8501` باز می‌شود. اگر پورت اشغال بود:
`python -m streamlit run app\ui\dashboard.py --server.port 8502`.

## بررسی سلامت نصب

| بررسی | دستور | نتیجه سالم |
|---|---|---|
| تست‌ها | `python -m pytest -q` | بدون `failed` (skipped وابسته به torch/Streamlit/وزن است) |
| تنظیمات | `python scripts\kql.py settings` | JSON با `interval`، `models`، `venues` |
| مدل‌ها | `python scripts\kql.py models` | baseline available؛ Kronos بعد از دانلود weight |
| دیتابیس | `python scripts\kql.py data status` | ساخت جدول‌ها بدون خطا (حتی اگر خالی باشد) |
| پیش‌بینی | `python scripts\kql.py forecast --symbol SYNTH-DEMO --model baseline-bootstrap` | جدول P10/P50/P90 و شماره run |
| داشبورد | `python -m streamlit run app\ui\dashboard.py` | صفحه روی پورت 8501 |

## به‌روزرسانی، نسخه پشتیبان و حذف

```powershell
# به‌روزرسانی کد و وابستگی‌ها
git pull
python -m pip install -r requirements-p0.txt -r requirements-ui.txt
python -m pytest -q

# ارتقای commit مدل، فقط در صورت نیاز
git -C vendor\Kronos fetch
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
```

- **پشتیبان:** `artifacts\` (دیتابیس `kql.sqlite3`، وزن‌ها، گزارش‌ها) و فایل `.env` را کپی کنید.
  داده و گزارش‌ها در Git نیستند و با `git pull` پاک نمی‌شوند.
- **بازنشانی دیتابیس:** فقط فایل `artifacts\kql.sqlite3` را (پس از پشتیبان) حذف کنید؛ با اجرای بعدی
  دوباره ساخته می‌شود.
- **حذف کامل:** `.venv`، `vendor\Kronos` و `artifacts\` را حذف کنید. **قبل از حذف `artifacts`**
  از وزن‌ها و گزارش‌ها نسخه پشتیبان بگیرید.

## نصب روی Linux / macOS

```bash
git clone https://github.com/ho3eines/KronosQuantLab.git
cd KronosQuantLab
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-p0.txt -r requirements-ui.txt
git clone https://github.com/shiyu-coder/Kronos.git vendor/Kronos
git -C vendor/Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a
python -m pytest -q
export KQL_ARTIFACTS_DIR="$HOME/kql_artifacts"   # اختیاری؛ یا از .env استفاده کنید
python scripts/kql.py settings
```

## خطاهای رایج نصب

| نشانه | علت و راه‌حل |
|---|---|
| `py` شناخته نمی‌شود | Python در PATH نیست؛ نصب مجدد با گزینه Add to PATH، یا از `python` استفاده کنید. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` و دوباره فعال کنید. |
| خطای build برای pandas/numpy | نسخه Python اشتباه است؛ 3.11 یا 3.12 نصب کنید (نه 3.13). |
| نصب torch خیلی طول می‌کشد/حجم زیاد | طبیعی است؛ برای CPU همان دستور requirements کافی است. |
| `Kronos source not found` | پوشه `vendor/Kronos` ساخته نشده یا commit اشتباه است؛ گام ۵ را تکرار کنید. |
| `weights not found in ...` | گام ۹ (دانلود وزن) اجرا نشده است. |
| `license unknown` | model card مجوز ندارد؛ صفحه مدل را بخوانید و با `--accept-unknown-license` تأیید کنید. |
| `could not fetch ...` یا `no Binance market-data host answered` | شبکه/فیلترینگ؛ `KQL_BINANCE_*` را تنظیم کنید یا از `data import --csv` / `NOBITEX:` استفاده کنید. |
| `streamlit: command not found` | `requirements-ui.txt` نصب نشده یا venv فعال نیست. |
| پورت 8501 اشغال است | `--server.port 8502`. |
| متن فارسی در کنسول به‌هم‌ریخته | `chcp 65001` یا از داشبورد استفاده کنید. |
| `database is locked` | داشبورد یا پردازه دیگری دیتابیس را باز نگه داشته؛ آن را ببندید و دوباره اجرا کنید. |

## تنظیمات (همه غیرمحرمانه)

همه مقادیر از متغیر محیطی یا فایل `.env` خوانده می‌شوند (نمونه در `.env.example`). برای دیدن مقدار مؤثر:

```powershell
.\.venv\Scripts\python scripts\kql.py settings
```

### ۱) داده بازار: دو دامنه Binance با جایگزینی خودکار

| تنظیم | پیش‌فرض | توضیح |
|---|---|---|
| `KQL_BINANCE_BASE_URL` | `https://data-api.binance.vision` | دامنه اصلی داده عمومی |
| `KQL_BINANCE_FALLBACK_URLS` | `https://api.binance.com` | دامنه جایگزین؛ با HTTP **451** یا **403** خودکار فعال می‌شود |

در صورت خطای جغرافیایی، دریافت از ابتدا روی دامنه بعدی تکرار می‌شود (ردیف‌های دو دامنه هرگز در یک سری مخلوط نمی‌شوند) و دامنه‌ای که پاسخ داده تا پایان همان پردازه به خاطر سپرده می‌شود. اگر هر دو دامنه مسدود باشند، پیام روشن می‌دهد و `data import --csv` جایگزین است.

### ۲) مدل Kronos با وزن‌های واقعی

| مدل | `model_id` | `tokenizer_id` | پارامتر | طول زمینه |
|---|---|---|---|---|
| small | `NeoQuasar/Kronos-small` | `NeoQuasar/Kronos-Tokenizer-base` | حدود 24.7M | 512 |
| base | `NeoQuasar/Kronos-base` | `NeoQuasar/Kronos-Tokenizer-base` | حدود 102.3M | 512 |

دانلود فقط با `p0.py models --download --yes` انجام می‌شود و مجوز model card پیش از دانلود نشان داده می‌شود؛ اگر مجوز اعلام نشده باشد، تأیید صریح `--accept-unknown-license` لازم است. شناسه‌ها در `app/core/config.py` تعریف شده‌اند و با `kql.py models` نمایش داده می‌شوند.

### ۳) آستانه‌های تصمیم (P3)

| پارامتر | پیش‌فرض | معنا |
|---|---|---|
| `validation_alpha` | 0.05 | سطح معناداری کران بالای ARI تحت فرضیه صفر |
| `validation_null_ari_max` | خودکار | حداکثر ARI تحت فرضیه صفر؛ `None` یعنی از جایگشت‌ها کالیبره شود |
| `validation_stability_threshold` | خودکار | کمینه ARI برای آزمون پایداری؛ `None` یعنی برابر کران صفر |
| `n_permutations` | 100 | تعداد جایگشت بازده‌ها برای ساخت توزیع صفر |
| `n_bootstrap` | 50 | تعداد نمونه بوت‌استرپ بلوکی برای سنجش پایداری |
| `forward_window` | 10 | تعداد کندل «رژیم آینده» که ARI با آن سنجیده می‌شود |

روش: رژیم هر کندل (روند × نوسان از داده گذشته) با رژیم `forward_window` کندل بعدی روی **همان کندل‌ها** با شاخص ARI مقایسه می‌شود. سپس بازده‌ها جایگشت می‌خورند تا معلوم شود ARI تحت تصادف چقدر است، و بوت‌استرپ بلوکی پایداری آماره را می‌سنجد. نتیجه در `artifacts/reports/threshold_validation_*` ذخیره می‌شود و شامل `passed`، توزیع صفر و بازه بوت‌استرپ است. عبور از این آزمون یعنی برچسب‌ها از تصادف جدا و تکرارپذیرند؛ **یعنی قواعد سودآورند نیست**.

```powershell
.\.venv\Scripts\python scripts\kql.py validate --symbol BTCUSDT --alpha 0.05 --n-permutations 100 --n-bootstrap 50
```

### ۴) نمونه‌گیری مدل و شبیه‌سازی معاملات

| گروه | پارامتر | پیش‌فرض |
|---|---|---|
| نمونه‌گیری | `sample_count` (نام دیگر `--n-paths`) | 20 |
| نمونه‌گیری | `temperature` (T) | 1.0 |
| نمونه‌گیری | `top_p` | 0.9 |
| نمونه‌گیری | `top_k` | 0 (غیرفعال) |
| پرتفوی | `n_symbol_hold` | 50 |
| پرتفوی | `n_symbol_drop` | 5 |
| پرتفوی | `hold_thresh` | 5 کندل |
| پرتفوی | `time_range` | `--start`/`--end` |
| پرتفوی | `account` | 100,000,000 |
| تک‌دارایی | `--cash` | 10,000 |

`sample_count` تعداد مسیرهای نمونه‌گیری‌شده است؛ هرچه بیشتر، ارزیابی عدم‌قطعیت دقیق‌تر و اجرا کندتر. دمای بالاتر مسیرهای جسورانه‌تر و دمای پایین‌تر محافظه‌کارانه‌تر می‌سازد. `top_p`/`top_k` نمونه‌گیری را متمرکز می‌کنند.

### ۵) پنجره و بازه کندل

| پارامتر | پیش‌فرض | محدوده |
|---|---|---|
| `lookback` | 400 کندل | حداکثر 512 |
| `pred_len` (`MAX_HORIZON`) | 96 کندل | حداکثر 96 |
| `interval` | `1d` | `1h`، `4h`، `1d` |

بازه‌ها در پایگاه داده جدا نگهداری می‌شوند (`candles.interval` و `forecast_runs.interval`) و تنظیمات نمونه‌گیری هر اجرا (`temperature`، `top_p`، `top_k`) نیز در `forecast_runs` ثبت می‌شود. سالانه‌سازی نوسان/شارپ از طول کندل محاسبه می‌شود (365 برای روزانه، 2190 برای ۴ ساعته، 8760 برای ۱ ساعته).

## صرافی‌ها و منابع داده (Binance، Nobitex، Alpari)

هر نماد به یک «venue» تعلق دارد. نماد بدون پیشوند یعنی Binance؛ بقیه با پیشوند ذخیره می‌شوند
(`NOBITEX:BTCIRT`، `ALPARI:EURUSD`) تا نمادهای هم‌نام دو صرافی در پایگاه داده قاطی نشوند.

| venue | پیشوند نماد | تقویم | اتصال | احراز هویت |
|---|---|---|---|---|
| Binance | — (`BTCUSDT`) | ۲۴/۷، ۳۶۵ روز | kline عمومی؛ `data-api.binance.vision` و جایگزین خودکار `api.binance.com` | ندارد |
| Nobitex | `NOBITEX:` (`NOBITEX:BTCIRT`) | ۲۴/۷، ۳۶۵ روز | OHLC عمومی `GET /market/udf/history` | ندارد (هیچ توکنی خوانده نمی‌شود) |
| Alpari | `ALPARI:` (`ALPARI:EURUSD`) | FX، ۲۵۲ روز | خروجی CSV از MetaTrader 5 | ندارد؛ ورود به حساب انجام نمی‌شود |

### Nobitex

```powershell
& $k[0] $k[1] data update --symbols NOBITEX:BTCIRT NOBITEX:ETHIRT --interval 1d
& $k[0] $k[1] forecast --symbol NOBITEX:BTCIRT --model baseline-bootstrap --interval 4h
& $k[0] $k[1] data venues
```

- حداکثر ۵۰۰ کندل در هر پاسخ؛ آداپتور از پنجره‌های زمانی صریح و **از جدید به قدیم** استفاده می‌کند،
  پس به معنای پارامتر `page` (که در مستندات نیامده) وابسته نیست.
- `s` می‌تواند `no_data` یا `error` باشد؛ هر دو صریح مدیریت می‌شوند و حدس زده نمی‌شوند.
- مرز کندل‌ها به وقت ایران است. timestamp **دست‌نخورده** ذخیره می‌شود؛ «خارج از شبکه UTC» و
  شکاف‌ها به‌صورت هشدار گزارش می‌شوند و باعث رد داده نمی‌شوند (با `data import --strict` می‌توان
  سخت‌گیر شد).
- نوبیتکس فقط حجم پایه را می‌دهد؛ `amount` به‌صورت `volume × close` ساخته می‌شود و در خروجی
  `notes` همین موضوع ذکر می‌شود.
- تنظیم‌ها: `KQL_NOBITEX_BASE_URL`، `KQL_NOBITEX_REQUEST_INTERVAL` (فاصله بین صفحه‌ها)،
  `KQL_NOBITEX_TIMEOUT`، `KQL_NOBITEX_RETRIES`، `KQL_NOBITEX_HISTORY_START`.

### Alpari (MetaTrader 5)

آلپاری API عمومی و بدون‌کلید برای کندل‌ها ندارد؛ داده از ترمینال MT5 می‌آید که ورود به حساب لازم دارد.
این پروژه هیچ ورود/حساب/سفارشی ندارد، پس مسیر پشتیبانی‌شده **خروجی گرفتن** است:

1. در MetaTrader 5: `Toolbox → History`، نماد و تایم‌فریم را انتخاب کنید.
2. راست‌کلیک → `Export` → `CSV`.
3. فایل را وارد کنید:

```powershell
& $k[0] $k[1] data import --symbol ALPARI:EURUSD --csv .\EURUSD_1d.csv --interval 1d --format mt5
# اگر زمان سرور بروکر UTC نیست، اختلاف ساعت را صریح بدهید (مثلاً UTC+3):
& $k[0] $k[1] data import --symbol ALPARI:EURUSD --csv .\EURUSD_1d.csv --interval 1d --format mt5 --tz-offset 3
```

- جداکننده tab/`;`/`,`، هدرهای `<DATE>/<TIME>` یا `Date/Time`، تاریخ‌های روز-اول و
  `TICKVOL` (به‌جای حجم واقعی که در FX صفر است) پشتیبانی می‌شوند.
- زمان خروجی «زمان سرور بروکر» است و حدس زده نمی‌شود: با `--tz-offset` تبدیل می‌شود و
  انتخاب شما در گزارش import ثبت می‌شود.
- تقویم FX: سالانه‌سازی ۲۵۲ روز (نه ۳۶۵) و شکاف‌های آخر هفته/تعطیلات طبیعی‌اند؛ گزارش
  می‌شوند ولی داده را رد نمی‌کنند. `--strict` همه شکاف‌ها را خطا می‌کند.
- اگر فاصله کندل‌ها با `--interval` نخواند (مثلاً خروجی ۱ ساعته با `--interval 1d`)،
  import با پیام روشن رد می‌شود.
- داشبورد و CLI از همان داده ذخیره‌شده استفاده می‌کنند؛ نیازی به اتصال زنده نیست.

پرتفوی با نمادهای چند venue در یک اجرا پذیرفته نمی‌شود، چون تقویم و سالانه‌سازی مشترک
تعریف‌شده‌ای ندارد.

## کار روزمره (P1 تا P5)

مدل‌ها: `baseline-bootstrap` (داخلی، بدون وزن)، `kronos-small`، `kronos-base`.

```powershell
$k = ".\.venv\Scripts\python", "scripts\kql.py"
& $k[0] $k[1] settings
& $k[0] $k[1] data update --symbols BTCUSDT ETHUSDT --interval 1d    # P1: کندل‌های جدید به SQLite
& $k[0] $k[1] data status --interval 1d
& $k[0] $k[1] models
& $k[0] $k[1] forecast  --symbol BTCUSDT --model kronos-small --horizon 30 --sample-count 20 `
      --temperature 1.0 --top-p 0.9 --top-k 0                         # P2: P10/P50/P90
& $k[0] $k[1] calibrate --symbol BTCUSDT --model kronos-small          # P2: پوشش واقعی و ضریب کالیبراسیون
& $k[0] $k[1] validate  --symbol BTCUSDT                              # P3: کالیبراسیون آستانه‌ها
& $k[0] $k[1] backtest  --symbol BTCUSDT --model kronos-small          # P4: تک‌دارایی
& $k[0] $k[1] portfolio --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT `
      --n-symbol-hold 3 --n-symbol-drop 1 --hold-thresh 5 --account 100000000 `
      --time-range 2024-01-01 2025-12-31                                # P4: پرتفوی Qlib-style
& $k[0] $k[1] paper init                                             # P5: حساب فرضی
& $k[0] $k[1] paper step --symbol BTCUSDT --model kronos-small       # یک بار در هر کندل
& $k[0] $k[1] paper status
& $k[0] $k[1] data update --symbols NOBITEX:BTCIRT --interval 1d       # P1: نوبیتکس (عمومی)
& $k[0] $k[1] data import --symbol ALPARI:EURUSD --csv EURUSD_1d.csv --format mt5   # P1: خروجی MT5
.\.venv\Scripts\streamlit run app\ui\dashboard.py                    # داشبورد
```

بدون اینترنت و بدون وزن هم می‌شود همه مسیر را امتحان کرد: `data demo` یک سری ساختگی با نماد `SYNTH-DEMO` می‌سازد (`--interval 1h` هم ممکن است) و `baseline-bootstrap` نیازی به وزن ندارد. اعداد این حالت هیچ معنایی برای بازار واقعی ندارند.

هر اجرای `benchmark`، `evaluate`، `calibrate`، `validate`، `backtest` و `portfolio` پوشه تازه‌ای در `artifacts\reports\` می‌سازد و چیزی را بازنویسی نمی‌کند.

## قواعد زمانی (کنترل look-ahead)

- تصمیم پس از بسته‌شدن کندل t و فقط با کندل‌های ۰ تا t گرفته می‌شود.
- اجرا در قیمت باز کندل t+1، با کارمزد و اسلیپیج.
- فقط خرید و نگهداری یا نقد (بدون فروش استقراضی، بدون اهرم).
- کالیبراسیون روی مبدأهای قدیمی‌تر fit و روی مبدأهای جدیدتر سنجیده می‌شود.
- `validate` برای ساختن برچسب «آینده» از داده بعد از t استفاده می‌کند، اما آن برچسب‌ها فقط در گزارش می‌مانند و هرگز به تصمیم یا بک‌تست نمی‌رسند.

## پرتفوی Qlib-style

امتیاز هر نماد در کندل t، میانه (P50) بازده پیش‌بینی‌شده تا افق مشخص است. سپس:

1. `n_symbol_hold` نماد برتر نگه داشته می‌شوند؛
2. حداکثر `n_symbol_drop` نماد از بدترین‌ها فروخته می‌شوند، به شرطی که حداقل `hold_thresh` کندل نگه داشته شده باشند؛
3. نمادهای بهترِ غیرموجود با وزن مساوی `1 / تعداد نگهداری` خریداری می‌شوند؛
4. اجرا در باز کندل بعد با کارمزد و اسلیپیج؛ تعداد موقعیت‌ها هرگز از سقف بیشتر و نقد هرگز منفی نمی‌شود.

اگر تعداد نمادها کمتر از `n_symbol_hold` باشد، سقف به تعداد موجود کاهش می‌یابد و در گزارش نوشته می‌شود. نمادی که پیش‌بینی‌اش شکست بخورد از انتخاب کنار گذاشته می‌شود (حدس زده نمی‌شود).

## مستندات

| سند | محتوا |
|---|---|
| [docs/STATUS.md](docs/STATUS.md) | وضعیت انجام‌شده/انجام‌نشده، شواهد تست و قدم‌های بعدی |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | انطباق خط‌به‌خط با تنظیمات درخواستی (هر پارامتر + باقی‌مانده) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | ماژول‌ها و جریان داده |
| [docs/DECISIONS.md](docs/DECISIONS.md) | تصمیم‌های فنی و دلیل آن‌ها |
| [docs/P0_plan.md](docs/P0_plan.md) | تحقیق منبع مدل و API واقعی Kronos |
| [docs/P0_environment_report.md](docs/P0_environment_report.md) | گزارش محیط |
| [CHANGELOG.md](CHANGELOG.md) | تغییرات |

## عیب‌یابی

| نشانه | اقدام |
|---|---|
| Kronos خیلی کند است | `--n-paths 10`، `--n-origins 8`، `--n-decisions 12`، `--rebalance-every 5`. پیش‌بینی‌ها در `artifacts\forecast_cache` ذخیره می‌شوند (کلید cache شامل مدل، نمونه‌گیری، seed و دقیقاً همان پنجره است). |
| خطای حافظه در P0 | `--batch-size 5` |
| `could not fetch ...` یا `no Binance market-data host answered` | شبکه به هیچ‌کدام از دو دامنه دسترسی ندارد؛ `KQL_BINANCE_BASE_URL`/`KQL_BINANCE_FALLBACK_URLS` را تنظیم کنید یا از `data import --csv` استفاده کنید. |
| `gap` هنگام به‌روزرسانی داده | برای Binance سخت‌گیر است و چیزی ذخیره نمی‌شود تا سری ناقص وارد نشود؛ برای Nobitex/Alpari (تقویم بومی) فقط هشدار است. `--strict` را برای رد قطعی به کار ببرید. |
| `factor = None` در کالیبراسیون | مبدأ کافی نیست (برای سطح ۰٫۸ حداقل ۴ مبدأ کالیبراسیون)؛ `--n-origins` را زیاد کنید. |
| `NOT PASSED` در `validate` | برچسب‌های رژیم از تصادف جدا نیستند یا پایدار نیستند؛ آستانه‌های P3 را روی این تاریخچه کالیبره نکنید. تاریخچه بلندتر یا `--forward-window` بزرگ‌تر را امتحان کنید. |
| `lookback ... exceeds` یا `horizon ... MAX_HORIZON` | سقف‌ها 512 و 96 کندل‌اند؛ مقدار کوچک‌تری بدهید. |
| `Nobitex` خطای TLS/شبکه | آدرس `KQL_NOBITEX_BASE_URL` را بررسی کنید؛ در صورت مسدود بودن، از `data import --csv` استفاده کنید. هیچ توکنی لازم نیست. |
| `data import --format mt5` خطا داد | تایم‌فریم خروجی MT5 باید با `--interval` بخواند؛ برای زمان سرور بروکر `--tz-offset` بدهید. |
| `weights missing` | گام P0 ‏(`p0.py models --download --yes`) اجرا نشده است. |
| `license unknown` | model card مجوزی اعلام نکرده؛ صفحه مدل را بخوانید و فقط در صورت پذیرش `--accept-unknown-license` بدهید. |
