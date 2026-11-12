# معماری

رابط‌ها (CLI و داشبورد) هیچ منطقی ندارند؛ هر دو فقط `app/services.py` و ماژول‌های دامنه را صدا می‌زنند.

وضعیت اجرا (چه انجام شده و چه نشده، با شاهد): [`STATUS.md`](STATUS.md).
بازبینی کد در برابر مستندات: [`AUDIT.md`](AUDIT.md).

## ماژول‌ها

| مسیر | مرحله | مسئولیت |
|---|---|---|
| `app/core/config.py` | — | مسیرها، شناسه مدل‌ها و توکنایزر، دامنه‌های Binance، سقف پنجره، تنظیمات نمونه‌گیری و پرتفوی |
| `app/core/timeframes.py` | — | نگاشت بازه کندل (1h/4h/1d) به طول گام و تعداد کندل در سال |
| `app/core/venues.py` | — | فضای نام نماد (`VENUE:SYMBOL`)، تقویم ۲۴/۷ یا FX، سالانه‌سازی و افق سشن |
| `app/core/envfile.py` | — | بارگذاری `.env` بدون وابستگی (فقط `KQL_*`، اولویت متغیر محیطی) |
| `app/core/errors.py` | — | سلسله خطاهای قابل انتظار (`KQLError`) |
| `app/core/runs.py` | — | پوشه اجرا و نوشتن فایل بدون بازنویسی |
| `app/storage/db.py` | P1 | طرح SQLite و audit log فقط‌افزودنی |
| `app/data/http.py` | — | GET عمومی JSON با User-Agent ثابت (فقط خواندن) |
| `app/data/binance.py` | P0 | دریافت kline عمومی با جایگزینی خودکار دامنه در خطای 451/403 |
| `app/data/nobitex.py` | P1 | OHLC عمومی نوبیتکس (UDF، بدون توکن، پنجره‌های ۵۰۰ کندلی از جدید به قدیم) |
| `app/data/alpari.py` | P1 | خواندن خروجی CSV متاتریدر ۵ (بدون ورود به حساب)، تقویم FX و تبدیل صریح زمان |
| `app/data/validation.py` | P0 | اعتبارسنجی و پاک‌سازی محافظه‌کارانه |
| `app/data/engine.py` | P1 | provider ← اعتبارسنجی ← SQLite؛ به‌روزرسانی افزایشی چند نماد و چند بازه |
| `app/forecast/base.py` | P0 | قرارداد `Forecaster` و ساخت پنجره بدون نشت |
| `app/forecast/kronos_adapter.py` | P0 | Kronos از پوشه محلی، مسیرهای جداگانه |
| `app/forecast/weights.py` | P0 | مجوز، حجم و دانلود وزن‌ها |
| `app/forecast/baselines.py` | P2 | مدل پایه احتمالاتی (bootstrap بازده‌ها) |
| `app/forecast/registry.py` | P2 | نام ← مدل؛ cache پیش‌بینی روی دیسک |
| `app/forecast/service.py` | P2 | تولید و ذخیره P10/P50/P90 |
| `app/evaluation/metrics.py` | P0 | MAE، RMSE، sMAPE، quantile، پوشش |
| `app/evaluation/rolling.py` | P0 | ارزیابی rolling-origin و naive |
| `app/evaluation/benchmark.py` | P0 | زمان و منابع |
| `app/evaluation/report.py` | P0 | گزارش Markdown |
| `app/evaluation/calibration.py` | P2 | کالیبراسیون split-conformal بازه P10–P90 |
| `app/signals/regime.py` | P3 | رژیم روند × نوسان از داده گذشته |
| `app/signals/rules.py` | P3 | BUY / SELL / ABSTAIN و اندازه موقعیت |
| `app/signals/pipeline.py` | P3 | تنها نقطه برش تاریخچه: تصمیم در کندل t با داده ۰ تا t |
| `app/signals/validation.py` | P3 | کالیبراسیون آستانه‌ها: ARI، توزیع صفر با جایگشت، پایداری با بوت‌استرپ |
| `app/backtest/execution.py` | P4 | محاسبه fill با کارمزد و اسلیپیج |
| `app/backtest/engine.py` | P4 | بک‌تست walk-forward تک‌دارایی و معیارهای عملکرد |
| `app/backtest/portfolio.py` | P4 | شبیه‌ساز سبد Qlib-style (TopkDropout)، چند نماد، هم‌وزن و کارمزد |
| `app/paper/simulator.py` | P5 | حساب فرضی، سفارش معلق، audit |
| `app/services.py` | — | use-caseهای مشترک CLI و داشبورد |
| `app/ui/dashboard.py` | P5 | Streamlit؛ فقط نمایش و فراخوانی سرویس |
| `scripts/p0.py`، `scripts/kql.py` | — | CLI |

`app/api` (FastAPI) ساخته نشده است: داشبورد و CLI در همان پردازه سرویس‌ها را صدا می‌زنند و مصرف‌کننده دیگری وجود ندارد.

## جریان داده

```
provider(venue) ─► validate(policy) ─► SQLite(candles)   # Binance/Nobitex خودکار؛ Alpari فقط CSV
                          │ load_candles
                          ▼
     decide_at(df, t):  past = df[:t+1]          ← تنها برش تاریخچه؛ تقویم venue (24/7 یا fx)
          ├─ make_forecast(past) ─► paths ─► P10/P50/P90
          ├─ detect_regime(past.close)           (regime_series برداری، همان پیاده‌سازی)
          └─ decide(quantiles × ضریب کالیبراسیون, regime) ─► BUY/SELL/ABSTAIN + کسر هدف
                          │
          ┌───────────────┴───────────────┐
   run_backtest (P4)               paper.step (P5)
   اجرا در open کندل t+1           سفارش PENDING ─► fill در open کندل بعدی
   equity.csv / backtest.json      SQLite + audit_log

validate (P3):  close ─► current regime ─┐
                close ─► forward regime ─┴─► ARI ─► null (permutations) + bootstrap ─► thresholds

portfolio (P4): symbols × bars ─► P50 score per symbol ─► TopkDropout ─► open t+1 ─► equity/trades
```

## قراردادها

- **ترتیب ستون‌ها:** `open, high, low, close, volume, amount` (ترتیب Kronos).
- **Forecaster:** یک Protocol. Kronos، مدل پایه و مدل‌های جعلی تست‌ها همگی آن را پیاده می‌کنند.
- **بدون look-ahead:** `decide_at` تاریخچه را می‌بُرد و بقیه کد فقط همان را می‌بیند. تستی هست که آینده را دست‌کاری می‌کند و بررسی می‌کند تصمیم‌های قبلی تغییر نکنند.
- **کندل ذخیره‌شده تغییر نمی‌کند:** اگر provider مقدار متفاوتی برای کندل قدیمی بدهد، به‌عنوان تعارض گزارش می‌شود و ردیف ذخیره‌شده می‌ماند.
- **خطاها:** خرابی یک مدل، یک نماد، یک مبدأ یا یک تصمیم ثبت می‌شود و بقیه اجرا ادامه می‌یابد. تصمیم ناموفق یعنی «کاری نکن».
- **audit log:** با trigger پایگاه داده، UPDATE و DELETE روی آن رد می‌شود.
- **بدون اتصال معاملاتی:** تستی کد و وابستگی‌ها را برای کتابخانه صرافی، endpoint سفارش و واژه‌های مربوط به کلید API می‌گردد و در صورت یافتن شکست می‌خورد.

## محدودیت‌های شناخته‌شده

- بک‌تست تک‌دارایی و شبیه‌ساز paper همچنان تک‌دارایی‌اند. شبیه‌ساز paper در چند نماد، «کسر هدف» را نسبت به نقد به‌علاوه همان موقعیت حساب می‌کند، نه کل سبد؛ پرتفوی Qlib-style مسیر جداگانه و چندنمادی است.
- پرتفوی فقط با تقاطع تقویم نمادها کار می‌کند و همه نمادها باید یک venue باشند؛ نمادی که تاریخچه کوتاه‌تری دارد، بازه مشترک را کوتاه می‌کند.
- داده نوبیتکس به وقت ایران برش می‌خورد و timestamp آن بازچینی نمی‌شود؛ ناهنجاری شبکه/شکاف فقط هشدار است. `amount` آن مشتق (`volume × close`) است.
- آلپاری API عمومی ندارد؛ داده فقط از خروجی MT5 می‌آید و «زنده» نیست. زمان سرور بروکر با `--tz-offset` تبدیل می‌شود و شکاف تعطیلات طبیعی است.
- کالیبراسیون آستانه P3 «آینده» را برای ساختن برچسب هدف می‌بیند (نه برای تصمیم)؛ عبور از آن سودآوری را اثبات نمی‌کند.
- fill در قیمت باز با اسلیپیج ثابت مدل می‌شود؛ عمق بازار و fill جزئی مدل نشده است.
- ضریب کالیبراسیون برای هر افق یک عدد است و از گام پایانی همان افق به دست می‌آید.
