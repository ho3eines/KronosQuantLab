# بازبینی کد در برابر مستندات

آخرین به‌روزرسانی: **2026-11-12** · شاخه: `arena/fa97d41b-kronosquantlab`

این سند نتیجه یک بازبینی خط‌به‌خط است: هر ادعای README و `docs/` با کد مقایسه شد. سه لایه بررسی شد:

1. **تطبیق ماشینی** — مقادیر پیش‌فرض، پرچم‌های CLI، متغیرهای محیطی، شمارش تست‌ها، شماره تصمیم‌ها.
2. **اجرای واقعی** — همه دستورهای مستندشده که بدون اینترنت و بدون وزن مدل اجراشدنی‌اند، با مسیر
   `KQL_ARTIFACTS_DIR` موقت اجرا و خروجی‌شان با متن مستندات مقایسه شد.
3. **خواندن کد** — ادعاهای رفتاری (جایگزینی دامنه، صفحه‌بندی نوبیتکس، کالیبراسیون، تقویم، پرتفوی).

**نتیجه کوتاه:** هیچ بخشی از خط لوله «مستند شده ولی پیاده‌نشده» پیدا نشد. آنچه پیدا شد، عمدتاً
**مستندات قدیمی‌تر از کد** بود (عدد تست، شماره تصمیم، نام پیام خطا) و سه ضعف واقعی در کد که
مستندات ادعای بیشتری از آن داشتند. هر سه رفع و تست شد.

---

## ۱. تطبیق ماشینی — چه چیزی و با چه نتیجه‌ای

| بررسی | مقدار بررسی‌شده | نتیجه |
|---|---|---|
| مقادیر پیش‌فرض و ثابت‌ها (`app/core/config.py`، `PortfolioConfig`، `Costs`، `venues.py`، `timeframes.py`) | ۳۹ ادعا | ۳۹/۳۹ مطابق |
| پرچم‌های CLI در README و `docs/` در برابر `--help` واقعی | ۴۰ پرچم پروژه (از ۴۶ پرچم یکتای متن؛ بقیه مال ابزارهای بیرونی) | همه موجود و در دستور درست |
| متغیرهای `KQL_*` در کد در برابر `.env.example` و README | ۲۷ متغیر | ۲۷/۲۷ مستندشده؛ هیچ متغیر بی‌سندی وجود ندارد |
| ستون‌های SQLite (`candles`، `forecast_runs`) | `interval`، `temperature`، `top_p`، `top_k`، `n_paths` | مطابق ادعای مستندات |
| تصمیم‌های `docs/DECISIONS.md` | D1..D42 | پیوسته، بدون تکرار و بدون جاافتادگی |
| شمارش تست هر فایل در `STATUS.md` | ۱۶ فایل | مطابق `pytest --collect-only` (جمع ۲۰۷) |

نمونه‌ای از ادعاهای عددی که مستقیماً از کد خوانده و تأیید شدند: دامنه اصلی
`https://data-api.binance.vision`، جایگزین `https://api.binance.com`،
`NeoQuasar/Kronos-small` با `24.7M` و `NeoQuasar/Kronos-base` با `102.3M`، context 512،
`validation_alpha=0.05`، `n_permutations=100`، `n_bootstrap=50`، `lookback=400` با سقف 512،
`pred_len=96`، `n_symbol_hold=50`، `n_symbol_drop=5`، `hold_thresh=5`، `account=100_000_000`،
کارمزد ۱۰ و اسلیپیج ۵ بیسیس‌پوینت، بازه‌های `1h/4h/1d` با سالانه‌سازی ۸۷۶۰/۲۱۹۰/۳۶۵ و
تقویم FX با ۲۵۲ روز.

---

## ۲. اجرای عملی (روی داده ساختگی، بدون اینترنت)

| مسیر مستندشده | دستور | نتیجه |
|---|---|---|
| داده ساختگی | `data demo --rows 600` و `--interval 1h` | ✅ هر دو؛ `data status` بازه/گام/شکاف را نشان داد |
| جدول venueها | `data venues` | ✅ سه venue با ستون `public_api` و توضیح اتصال |
| اعتبارسنجی آستانه | `validate --n-permutations 20 --n-bootstrap 10` | ✅ ARI مشاهده‌شده، کران صفر، بازه بوت‌استرپ، آستانه خودکار، پوشه گزارش تازه |
| کالیبراسیون بازه | `calibrate --n-origins 10` | ✅ پوشش خام و کالیبره‌شده، `factor`، گزارش تازه |
| بک‌تست تک‌دارایی | `backtest --n-paths 10` | ✅ سطر strategy/buy_and_hold/cash، `equity.csv`، `trades.csv`، `decisions.csv`، `backtest.json` |
| پرتفوی | `portfolio --symbols … --n-symbol-hold 2` | ✅ `effective_hold`، بنچمارک هم‌وزن کیهان، `portfolio.json` |
| محافظ چند-venue | `portfolio --symbols ALPARI:EURUSD SYNTH-B` | ✅ خطای صریح: سبد باید تک‌venue باشد |
| تداخل `--time-range` و `--start` | `portfolio … --time-range … --start …` | ✅ خطای صریح «use either …» |
| paper | `paper init` / `step` / `status` | ✅ حساب ۱۰٬۰۰۰ فرضی، سفارش PENDING، fill در کندل بعد |
| ایمپورت CSV | `data import --symbol SYNTH-B --csv …` | ✅ ذخیره و سپس پیش‌بینی/پرتفوی روی همان داده |
| ایمپورت MT5 | `data import --format mt5 --tz-offset 3` | ✅ جداکننده tab، هدر `<DATE>`، تاریخ روز-اول، `TICKVOL`، گزارش تبدیل زمان |
| ناسازگاری تایم‌فریم | ایمپورت فایل روزانه با `--interval 4h` | ✅ رد با پیام روشن |
| `--strict` روی FX | ایمپورت MT5 با `--strict` | ✅ رد با `fatal_problems` |
| خطای شبکه | `data update --symbols BTCUSDT` | ✅ پیام `could not fetch …` (بدون داده نیمه‌کاره) |
| P0 | `p0.py benchmark/evaluate/models/report` | ✅ خطاهای روشن (نبود دیتاست/وزن/مجوز) بدون نوشتن گزارش جعلی |
| داشبورد | `ui` | ✅ دستور راه‌اندازی را چاپ می‌کند (خود Streamlit در این محیط نصب نیست) |

هر اجرا پوشه تازه در `artifacts/reports/` ساخت و چیزی بازنویسی نشد — همان‌طور که README می‌گوید.

---

## ۳. تناقض‌های مستندات که پیدا و اصلاح شد

| # | ادعای نادرست | واقعیت کد | اصلاح |
|---|---|---|---|
| ۱ | `ARCHITECTURE.md` جدول ماژول‌ها کامل بود | `app/core/envfile.py` (بارگذاری `.env`) در جدول نبود | ردیف ماژول اضافه شد |
| ۲ | `STATUS.md` در یک ردیف «۱۹۶ تست» | ۲۰۷ جمع‌آوری‌شده (۱۹۷ passed + ۱۰ skipped) | عدد اصلاح شد |
| ۳ | «DECISIONS شامل D1–D41» در `STATUS.md` و `REQUIREMENTS.md` | فایل ۴۲ تصمیم دارد (D42 = `.env`) | D1–D42 شد |
| ۴ | «۱۰ تست skip وابسته به torch/وزن/شبکه» | ۹ مورد torch/وزن + ۱ مورد نبود Streamlit | دلیل‌ها تفکیک شد |
| ۵ | پیام خطای `weights missing` در عیب‌یابی | پیام واقعی: `weights not found in …` | متن اصلاح شد |
| ۶ | فهرست «`--n-paths`، `--n-origins`، `--n-decisions`، `--rebalance-every`» به‌عنوان یک نسخه | `--n-origins` فقط `calibrate`، `--n-decisions` فقط `backtest`، `--rebalance-every` در `backtest`/`portfolio` | هر پرچم به دستور خودش نسبت داده شد |
| ۷ | «`factor = None` یعنی کمتر از ۴ مبدأ» | با `calib_fraction=0.5` برای سطح ۰٫۸ به **۸ مبدأ کل** (۴ مبدأ کالیبراسیون) نیاز است | توضیح دقیق شد |
| ۸ | شمار تست `tests/test_alpari.py` = ۸ | ۱۳ (پنج تست تازه) | عدد اصلاح شد |
| ۹ | پوشش موضوعی `test_portfolio.py` شامل «failover» | failover مربوط به `test_data`/`test_settings` است؛ این فایل «شکست پیش‌بینی» را پوشش می‌دهد | برچسب اصلاح شد |
| ۱۰ | کد خروج `validate` نامشخص بود | در حالت `NOT PASSED` کد خروج ۱ است | در README مستند شد |
| ۱۱ | `p0.py report` بی‌قید گزارش می‌نویسد | اگر `docs/P0_model_benchmark.md` موجود باشد بدون `--force` رد می‌شود | در README/STATUS مستند شد |
| ۱۲ | «`data demo` با هر تعداد ردیف» | اجرای دوباره با `--rows` متفاوت ۰ ردیف درج می‌کند و تعارض گزارش می‌دهد (کندل ذخیره‌شده تغییر نمی‌کند) | به عیب‌یابی اضافه شد |
| ۱۳ | ارجاع «کامیت کد: `08e87b2`» در STATUS/REQUIREMENTS | کد فعلی روی `07415e3` است | به‌روزرسانی شد |

---

## ۴. ضعف‌های واقعی کد (مستندات بیشتر از کد ادعا می‌کرد)

| # | مشکل | چرا مهم بود | رفع |
|---|---|---|---|
| ۱ | خروجی MT5 با انکودینگ **UTF-16** (حالت «Unicode» خود متاتریدر) خوانده نمی‌شد؛ فایل با cp1252 «decode» می‌شد و خطای گمراه‌کننده «no usable rows (check the DATE format)» می‌داد | مستندات پشتیبانی از خروجی MT5 را عمومی ادعا می‌کرد؛ کاربر ویندوز می‌توانست در همان گام اول گیر کند | `decode_bytes` با تشخیص BOM/NUL و fallback امن؛ انکودینگ در گزارش import ثبت می‌شود؛ پیام خطا انکودینگ را نام می‌برد |
| ۲ | CSV تک‌ردیفی باعث `UnboundLocalError` می‌شد (متغیر `median` فقط داخل شرط تعریف شده بود) | ورودی مرزی باید پیام روشن بدهد، نه traceback | مقدار پیش‌فرض `0` و گزارش `median_spacing` |
| ۳ | docstring ماژول نوبیتکس می‌گفت «forward» در حالی که کد «backward» صفحه‌بندی می‌کند | تناقض داخلی که خواننده را گمراه می‌کرد | متن اصلاح شد |
| ۴ | `scripts/p0_env_probe.py` مسیر `KQL_ARTIFACTS_DIR` را نادیده می‌گرفت | بقیه پروژه این متغیر را می‌شناسد؛ گزارش محیط جای دیگری می‌رفت | همان متغیر رعایت می‌شود |

پنج تست تازه در `tests/test_alpari.py` اضافه شد: UTF-16 با BOM، UTF-16 بدون BOM، cp1252،
CSV تک‌ردیفی، و تست مستقیم `decode_bytes`.

---

## ۵. ادعاهایی که تأیید شدند (نمونه‌های مهم)

- **Binance:** جایگزینی فقط روی 451/403، بازگشت از `startTime` اولیه روی دامنه بعدی (ردیف دو
  دامنه قاطی نمی‌شود)، و به‌خاطرسپاری دامنه سالم تا پایان پردازه.
- **Nobitex:** `GET /market/udf/history` بدون توکن؛ `from`/`to` ثانیه‌ای؛ پنجره‌های ۵۰۰ کندلی از
  جدید به قدیم؛ بدون تکیه بر `page`؛ مدیریت `no_data`/`error`؛ `amount = volume × close`؛ timestamp
  بومی حفظ می‌شود.
- **Alpari:** فقط فایل؛ `--tz-offset` صریح و ثبت‌شده؛ تقویم FX با ۲۵۲ روز و شکاف‌های هشدار (نه خطا).
- **کالیبراسیون بازه:** ضریب fit‌شده روی بازه دیگر هرگز اعمال نمی‌شود (تست اختصاصی دارد).
- **کش پیش‌بینی:** کلید شامل مدل، `temperature/top_p/top_k`، `n_paths`، seed، پنجره ورودی و
  timestamp افق است؛ ورودی متفاوت یعنی کلید متفاوت.
- **کدلاست↔داخلی:** `decide_at` تنها نقطه برش تاریخچه است؛ تستی آینده را ×۴ می‌کند و نشان می‌دهد
  تصمیم‌های قبلی تغییر نمی‌کنند.
- **پرتفوی:** `TopkDropout` با سقف `n_symbol_hold`، حداکثر `n_symbol_drop` فروش پس از `hold_thresh`،
  وزن مساوی، اجرا در open کندل بعد، نقد غیرمنفی، بنچمارک هم‌وزن، و رد صریح سبد چند-venue.
- **امنیت/دامنه:** تست خودکار مخزن را برای `ccxt`، `python-binance`، endpoint سفارش/حساب و
  واژه‌های کلید API می‌گردد؛ audit log با trigger فقط‌افزودنی است.
- **داشبورد:** ۱۰ تب، بدون منطق دامنه، فقط فراخوانی `app/services.py`.

---

## ۶. چیزهایی که هنوز «تأیید نشده» است، نه «پیاده‌نشده»

این‌ها همان ردیف‌های 🟡/⬜ در [`STATUS.md`](STATUS.md) هستند و با بازبینی کد قابل بستن نیستند:

| مورد | چرا اینجا بسته نشد |
|---|---|
| درخواست زنده Binance / Nobitex | شبکه این محیط اجازه نمی‌دهد؛ کد و تست آفلاین آماده است |
| وزن‌های Kronos + مجوز model card | بدون `vendor/Kronos` و بدون دسترسی Hugging Face؛ ۱۰ تست آداپتور skip می‌شوند |
| `p0.py benchmark/evaluate` واقعی | به وزن + torch + داده واقعی نیاز دارد |
| رندر داشبورد | Streamlit در این محیط نصب نیست؛ فقط import/compile/تست‌های CLI بررسی شده |
| ویندوز/PowerShell | گزارش محیط فعلی از لینوکس است |
| CI و coverage | هنوز هیچ workflow‌ای وجود ندارد (N9) |

---

## ۷. بازتولید این بررسی

```powershell
# ۱) تست و کیفیت کد (باید بدون failed باشد)
python -m pytest -q
ruff check app scripts tests --select F,E9
mypy app scripts/kql.py scripts/p0.py --ignore-missing-imports

# ۲) صحت مستندات در برابر CLI
python scripts/kql.py --help
python scripts/kql.py data venues
python scripts/kql.py settings

# ۳) مسیر کامل آفلاین
$env:KQL_ARTIFACTS_DIR = "D:\kql_audit"
python scripts/kql.py data demo --rows 600
python scripts/kql.py forecast --symbol SYNTH-DEMO --n-paths 10
python scripts/kql.py validate --symbol SYNTH-DEMO --n-permutations 20 --n-bootstrap 10
python scripts/kql.py backtest --symbol SYNTH-DEMO --n-paths 10
python scripts/kql.py paper init
python scripts/kql.py paper step --symbol SYNTH-DEMO
```
