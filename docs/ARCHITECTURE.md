# معماری (وضعیت P0)

فقط ماژول‌هایی که در P0 کد دارند ساخته شده‌اند. `storage` (SQLite)، `api` (FastAPI) و `ui` (Streamlit) هنوز وجود ندارند، چون P0 به آن‌ها نیاز ندارد؛ نتایج P0 فایل‌های JSON/CSV/NPY هستند.

## ماژول‌ها

| مسیر | مسئولیت | وابستگی سنگین |
|---|---|---|
| `app/core/config.py` | مسیرها، شناسه و revision مدل‌ها، ترتیب ستون‌ها، تنظیمات نمونه‌گیری | — |
| `app/core/errors.py` | سلسله خطاهای قابل انتظار (`KQLError`) | — |
| `app/core/runs.py` | پوشه اجرا و نوشتن فایل بدون بازنویسی | — |
| `app/data/binance.py` | دریافت kline عمومی و تبدیل نوع | pandas |
| `app/data/validation.py` | اعتبارسنجی و پاک‌سازی محافظه‌کارانه OHLCV | pandas |
| `app/forecast/base.py` | قرارداد `Forecaster`، ساخت پنجره بدون نشت، کنترل شکل خروجی | pandas |
| `app/forecast/kronos_adapter.py` | بارگذاری Kronos از پوشه محلی و تولید مسیرهای جداگانه | torch (lazy) |
| `app/forecast/weights.py` | بررسی مجوز/حجم و دانلود وزن‌ها | huggingface_hub (lazy) |
| `app/evaluation/metrics.py` | MAE، RMSE، sMAPE، quantile، پوشش | numpy |
| `app/evaluation/rolling.py` | ارزیابی rolling-origin و baseline ساده | numpy |
| `app/evaluation/benchmark.py` | زمان، RAM، CPU، VRAM، افزایش مرحله‌ای مسیرها | psutil |
| `app/evaluation/report.py` | ساخت گزارش Markdown از نتایج ماشینی | — |
| `scripts/p0.py` | تنها نقطه ورود CLI؛ منطق ندارد، فقط ماژول‌ها را به هم وصل می‌کند | — |
| `scripts/p0_env_probe.py` | شناسایی محیط، فقط کتابخانه استاندارد | — |

## جریان داده

```
Binance klines ──► raw/*.json (دست‌نخورده)
                     │ validate_ohlcv
                     ▼
                  clean/*.csv ──► make_window(origin, lookback, horizon)
                                     │ context: فقط ردیف‌های قبل از origin
                                     ▼
                         Forecaster.sample_paths(context, future_ts, n_paths, seed)
                                     │ آرایه (n_paths, horizon, 6)
                                     ▼
                         summarize ──► metrics.csv / evaluation.json ──► report
```

## قراردادها

- **ترتیب ستون‌ها** همه‌جا `open, high, low, close, volume, amount` است (همان ترتیب Kronos).
- **Forecaster** یک Protocol است. Kronos و مدل جعلی تست‌ها هر دو آن را پیاده می‌کنند؛ ارزیابی و benchmark از مدل خبر ندارند.
- **مقادیر واقعی آینده** هرگز به forecaster داده نمی‌شوند؛ `make_window` آن‌ها را جدا نگه می‌دارد.
- **خطاها:** هر خطای قابل انتظار زیرکلاس `KQLError` است. خرابی یک مدل یا یک مبدأ ثبت می‌شود و اجرای بقیه ادامه می‌یابد.
- **بدون بازنویسی:** هر اجرا پوشه خودش را دارد و فایل‌ها با حالت انحصاری نوشته می‌شوند.
- **بدون شبکه در زمان inference:** وزن‌ها فقط از پوشه محلی بارگذاری می‌شوند.

## مراحل آینده (فقط طرح؛ پیاده‌سازی نشده)

| مرحله | افزوده‌ها |
|---|---|
| P1 Data Engine | `app/storage` با SQLite، چند دارایی، به‌روزرسانی روزانه، provider دوم |
| P2 Forecast & Calibration | ارزیابی rolling گسترده‌تر، کالیبراسیون خارج از نمونه |
| P3 Signal & Risk Research | رژیم بازار، BUY/SELL/ABSTAIN، اندازه موقعیت؛ فقط پژوهشی |
| P4 Backtesting | walk-forward، کارمزد، اسلیپیج، کنترل look-ahead |
| P5 Paper Trading & Dashboard | شبیه‌ساز محلی، audit، ‏Streamlit |

ورود به هر مرحله فقط پس از تأیید صریح کاربر.
