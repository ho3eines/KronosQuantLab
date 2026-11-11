# معماری

رابط‌ها (CLI و داشبورد) هیچ منطقی ندارند؛ هر دو فقط `app/services.py` و ماژول‌های دامنه را صدا می‌زنند.

## ماژول‌ها

| مسیر | مرحله | مسئولیت |
|---|---|---|
| `app/core/config.py` | — | مسیرها، شناسه مدل‌ها، ترتیب ستون‌ها، ثابت‌ها |
| `app/core/errors.py` | — | سلسله خطاهای قابل انتظار (`KQLError`) |
| `app/core/runs.py` | — | پوشه اجرا و نوشتن فایل بدون بازنویسی |
| `app/storage/db.py` | P1 | طرح SQLite و audit log فقط‌افزودنی |
| `app/data/binance.py` | P0 | دریافت kline عمومی |
| `app/data/validation.py` | P0 | اعتبارسنجی و پاک‌سازی محافظه‌کارانه |
| `app/data/engine.py` | P1 | provider ← اعتبارسنجی ← SQLite؛ به‌روزرسانی افزایشی چند نماد |
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
| `app/backtest/execution.py` | P4 | محاسبه fill با کارمزد و اسلیپیج |
| `app/backtest/engine.py` | P4 | بک‌تست walk-forward و معیارهای عملکرد |
| `app/paper/simulator.py` | P5 | حساب فرضی، سفارش معلق، audit |
| `app/services.py` | — | use-caseهای مشترک CLI و داشبورد |
| `app/ui/dashboard.py` | P5 | Streamlit؛ فقط نمایش و فراخوانی سرویس |
| `scripts/p0.py`، `scripts/kql.py` | — | CLI |

`app/api` (FastAPI) ساخته نشده است: داشبورد و CLI در همان پردازه سرویس‌ها را صدا می‌زنند و مصرف‌کننده دیگری وجود ندارد.

## جریان داده

```
provider ─► validate ─► SQLite(candles)
                          │ load_candles
                          ▼
     decide_at(df, t):  past = df[:t+1]          ← تنها برش تاریخچه
          ├─ make_forecast(past) ─► paths ─► P10/P50/P90
          ├─ detect_regime(past.close)
          └─ decide(quantiles × ضریب کالیبراسیون, regime) ─► BUY/SELL/ABSTAIN + کسر هدف
                          │
          ┌───────────────┴───────────────┐
   run_backtest (P4)               paper.step (P5)
   اجرا در open کندل t+1           سفارش PENDING ─► fill در open کندل بعدی
   equity.csv / backtest.json      SQLite + audit_log
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

- بک‌تست و شبیه‌ساز تک‌دارایی‌اند. در شبیه‌ساز با چند نماد، «کسر هدف» نسبت به نقد به‌علاوه همان موقعیت حساب می‌شود، نه کل سبد.
- fill در قیمت باز با اسلیپیج ثابت مدل می‌شود؛ عمق بازار و fill جزئی مدل نشده است.
- ضریب کالیبراسیون برای هر افق یک عدد است و از گام پایانی همان افق به دست می‌آید.
