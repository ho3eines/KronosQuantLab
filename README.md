# Kronos Quant Lab

سامانه محلی پژوهشی برای ارزیابی مدل‌های پیش‌بینی Kronos-small و Kronos-base روی داده روزانه رمزارز.

> **فقط پژوهش.** این پروژه به هیچ حساب واقعی وصل نمی‌شود، کلید API نمی‌گیرد و سفارش ارسال نمی‌کند. هیچ سیگنال خرید/فروشی تولید نمی‌کند و هیچ پیش‌بینی‌ای تضمین رفتار بازار نیست.

## وضعیت

مرحله **P0** (امکان‌سنجی و مقایسه دو مدل). کد و تست‌های P0 نوشته شده‌اند. **benchmark واقعی روی وزن‌های اصلی هنوز اجرا نشده است**، چون محیط توسعه به Hugging Face و Binance دسترسی ندارد؛ باید با دستورهای زیر روی سیستم ویندوزی اجرا شود. `docs/P0_model_benchmark.md` با دستور `report` از نتایج همان اجرا ساخته می‌شود.

| سند | محتوا |
|---|---|
| [docs/P0_plan.md](docs/P0_plan.md) | تحقیق منبع مدل، API واقعی، وابستگی‌ها، ریسک‌ها |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | ماژول‌ها و جریان داده |
| [docs/DECISIONS.md](docs/DECISIONS.md) | تصمیم‌های فنی |
| [docs/P0_environment_report.md](docs/P0_environment_report.md) | گزارش محیط |
| [CHANGELOG.md](CHANGELOG.md) | تغییرات |

## پیش‌نیاز

- Windows 64-bit، ‏Python 3.10 تا 3.12 (نه 3.13+)، Git
- حدود 2 GB فضای آزاد (تخمین؛ دستور `models` حجم واقعی را پیش از دانلود نشان می‌دهد)
- اینترنت فقط برای نصب، دانلود وزن و دریافت داده؛ بقیه اجراها آفلاین‌اند

## اجرا (PowerShell، از ریشه مخزن)

```powershell
# ۰) شناسایی محیط — چیزی نصب نمی‌کند
py scripts\p0_env_probe.py

# ۱) محیط مجازی و وابستگی‌ها (نسخه Python را با خروجی گام ۰ تطبیق دهید)
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-p0.txt

# ۲) کد Kronos با commit ثابت
git clone https://github.com/shiyu-coder/Kronos.git vendor\Kronos
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a

# ۳) تست‌ها — بدون اینترنت و بدون وزن مدل
.\.venv\Scripts\python -m pytest -q

# ۴) مجوز، حجم و فضای دیسک وزن‌ها — چیزی دانلود نمی‌کند
.\.venv\Scripts\python scripts\p0.py models
# پس از خواندن خروجی:
.\.venv\Scripts\python scripts\p0.py models --download --yes

# ۵) داده روزانه BTCUSDT (endpoint عمومی، بدون credential)
.\.venv\Scripts\python scripts\p0.py data

# ۶) smoke: هر دو مدل، ۱ مسیر، افق ۷
.\.venv\Scripts\python scripts\p0.py benchmark --smoke
.\.venv\Scripts\python -m pytest -q -m checkpoint

# ۷) benchmark مرحله‌ای: ۱ ← ۵ ← ۲۰ مسیر، افق ۳۰
.\.venv\Scripts\python scripts\p0.py benchmark

# ۸) ارزیابی دقت در برابر baseline ساده (افق ۷، ۱۴، ۳۰)
.\.venv\Scripts\python scripts\p0.py evaluate

# ۹) ساخت docs\P0_model_benchmark.md
.\.venv\Scripts\python scripts\p0.py report
```

هر اجرای `benchmark` و `evaluate` پوشه تازه‌ای در `artifacts\reports\` می‌سازد و نتایج قبلی را بازنویسی نمی‌کند. `report` بدون `--force` گزارش موجود را بازنویسی نمی‌کند. برای گزینه‌ها: `python scripts\p0.py <command> --help`.

## عیب‌یابی

| نشانه | اقدام |
|---|---|
| گام ۷ یا ۸ خیلی کند است | گام ۶ زمان یک مسیر را نشان می‌دهد. با `--stages 1 5`، `--n-paths 10` یا `--n-origins 4` کوچک‌تر اجرا کنید؛ تعداد واقعی اجراشده در نتیجه ثبت می‌شود. |
| خطای حافظه | `--batch-size 5` مسیرها را در دسته‌های کوچک‌تر می‌سازد. |
| `could not fetch ... binance` | شبکه شما به Binance دسترسی ندارد. متغیر `KQL_BINANCE_BASE_URL` را ببینید (`.env.example`) یا خبر دهید تا منبع دیگری بررسی شود. |
| `license unknown` در گام ۴ | model card مجوزی اعلام نکرده است. صفحه مدل را بخوانید؛ فقط در صورت پذیرش، `--accept-unknown-license` را اضافه کنید. |
| `Kronos source not found` | گام ۲ اجرا نشده است. |
| GPU | پیش‌فرض CPU است. `--device auto` فقط وقتی از CUDA استفاده می‌کند که یک آزمون واقعی روی کارت موفق شود؛ دلیل انتخاب در نتیجه ثبت می‌شود. |
