# P0 — طرح اجرا و تحقیق منبع مدل

آخرین به‌روزرسانی: 2026-11-11 · وضعیت: **کد P0 پیاده‌سازی شده؛ وزن و داده واقعی هنوز دانلود نشده و benchmark واقعی اجرا نشده است.** دستورهای اجرا در `README.md` هستند.

برچسب‌ها: «بررسی‌شده» یعنی از کد یا API واقعی خوانده شده؛ «تأییدنشده» یعنی فرض یا دانسته قبلی که باید بررسی شود.

## ۱. منبع مدل (P0.2)

### ۱.۱ مخزن کد — بررسی‌شده

| مورد | مقدار |
|---|---|
| مخزن | https://github.com/shiyu-coder/Kronos |
| commit بررسی‌شده | `67b630e67f6a18c9e9be918d9b4337c960db1e9a` (2026-04-13) |
| مجوز کد | MIT، ‏Copyright (c) 2025 ShiYu (فایل `LICENSE`) |
| حجم clone (depth 1) | 26 MB |
| بسته pip | ندارد؛ کد با `from model import ...` از داخل مخزن وارد می‌شود |
| مقاله | arXiv:2508.02739 |

### ۱.۲ checkpointها

| مدل | شناسه Hugging Face | Tokenizer | context | پارامتر |
|---|---|---|---|---|
| Kronos-small | `NeoQuasar/Kronos-small` | `NeoQuasar/Kronos-Tokenizer-base` | 512 | 24.7M |
| Kronos-base | `NeoQuasar/Kronos-base` | `NeoQuasar/Kronos-Tokenizer-base` | 512 | 102.3M |

شناسه‌ها، context و تعداد پارامتر از README مخزن خوانده شده‌اند (بررسی‌شده). هر دو مدل از **یک tokenizer مشترک** استفاده می‌کنند.

موارد **تأییدنشده**، چون huggingface.co از sandbox در دسترس نیست:

- **مجوز وزن‌ها.** مجوز MIT مخزن GitHub لزوماً شامل وزن‌ها نیست. مجوز model cardها باید پیش از دانلود خوانده شود.
- **نام و حجم دقیق فایل‌ها.** تخمین از روی تعداد پارامتر با float32: حدود 100 MB برای small، حدود 410 MB برای base، و چند ده مگابایت برای tokenizer. جمع تخمینی حدود 0.55 GB.
- **revision.** تست رگرسیون خود مخزن این دو را pin کرده است: small = `901c26c1332695a2a8f243eb2f37243a37bea320`، tokenizer = `0e0117387f39004a9016484a186a908917e22426`. برای base هیچ revision در مخزن ثبت نشده و باید هنگام دانلود ثبت شود.
- **تاریخ پایان داده آموزشی** (بخش ۴ را ببینید).

### ۱.۳ API واقعی inference — بررسی‌شده از `model/kronos.py`

بارگذاری:

```python
from model import Kronos, KronosTokenizer, KronosPredictor
tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
predictor = KronosPredictor(model, tokenizer, device=None, max_context=512, clip=5)
```

`device=None` به ترتیب `cuda:0`، `mps`، `cpu` را انتخاب می‌کند. ما device را همیشه صریح می‌دهیم.

پیش‌بینی:

```python
predictor.predict(df, x_timestamp, y_timestamp, pred_len,
                  T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=True)
```

| مورد | رفتار واقعی |
|---|---|
| `df` | DataFrame با ستون‌های اجباری `open, high, low, close`؛ ‏`volume` و `amount` اختیاری |
| نبود `volume` | `volume` و `amount` صفر می‌شوند |
| نبود `amount` | برابر `volume × میانگین(open, high, low, close)` محاسبه می‌شود |
| NaN | `ValueError` |
| `x_timestamp`, `y_timestamp` | `pandas.Series` از نوع datetime (از `.dt` استفاده می‌شود)؛ `y_timestamp` باید از طرف ما ساخته شود |
| ویژگی‌های زمانی | `minute, hour, weekday, day, month` |
| نرمال‌سازی | z-score با میانگین و انحراف معیار **همان پنجره ورودی**، سپس clip به ‎±5 |
| خروجی | DataFrame با شکل `(pred_len, 6)`، ستون‌ها به ترتیب `open, high, low, close, volume, amount`، index برابر `y_timestamp` |
| context طولانی‌تر از 512 | خودکار کوتاه می‌شود |

`predict_batch(df_list, x_timestamp_list, y_timestamp_list, pred_len, ...)` همان کار را برای چند سری با طول یکسان انجام می‌دهد و فهرستی از DataFrame برمی‌گرداند.

### ۱.۴ نمونه‌گیری و seed — بررسی‌شده، با پیامد مهم

- `sample_count=N` ورودی را N بار تکرار می‌کند، N مسیر می‌سازد و سپس **`np.mean` روی مسیرها می‌گیرد**. API عمومی فقط میانگین را برمی‌گرداند؛ مسیرهای جداگانه در دسترس نیستند.
- پس `sample_count=20` برای محاسبه P10/P50/P90 **قابل استفاده نیست**.
- راه پیشنهادی بدون تغییر کد upstream: فراخوانی `predict_batch` با N نسخه از همان سری و `sample_count=1`. هر عنصر batch یک مسیر جداگانه است و نرمال‌سازی هر سری مستقل انجام می‌شود. جایگزین کندتر: N بار `predict` با `sample_count=1`.
- نمونه‌گیری با `torch.multinomial` و مولد سراسری torch انجام می‌شود. پارامتر seed وجود ندارد؛ کنترل فقط با `torch.manual_seed` پیش از فراخوانی ممکن است (تست رگرسیون upstream هم همین کار را می‌کند).
- مسیرهای یک batch از یک مولد مشترک نمونه می‌گیرند: به شرط ورودی مستقل‌اند، اما seed جداگانه برای هر مسیر ندارند. بازتولید دقیق فقط با همان seed، همان اندازه batch، همان device و همان نسخه torch قابل انتظار است؛ این در P0.5 آزمایش می‌شود.

## ۲. وابستگی‌ها و حجم تخمینی

`requirements.txt` مخزن Kronos: ‏`numpy`، `pandas==2.2.2`، `torch>=2.0.0`، `einops==0.8.1`، `huggingface_hub==0.33.1`، `matplotlib==3.9.3`، `tqdm==4.67.1`، `safetensors==0.6.2`.

حداقل پیشنهادی برای P0 (بدون matplotlib، Streamlit، FastAPI، Plotly):

| بسته | نسخه | دلیل | یادداشت |
|---|---|---|---|
| torch | 2.7.1 | inference | wheel ویندوز در PyPI: حدود 127 MB (2.15.0) تا 216 MB (2.7.1) |
| pandas | 2.2.2 | pin خود upstream | wheel ویندوز فقط برای Python 3.10 تا 3.12 |
| numpy | 2.2.6 | — | — |
| einops | 0.8.1 | pin upstream | — |
| huggingface_hub | 0.33.1 | دانلود وزن | — |
| safetensors | 0.6.2 | بارگذاری وزن | — |
| tqdm | 4.67.1 | در کد upstream وارد می‌شود | — |
| psutil | آخرین | اندازه‌گیری RAM/CPU | — |
| pytest | آخرین | تست | — |

حجم wheelها از API ‏PyPI خوانده شده است. تأییدنشده: اینکه wheel ویندوزی torch در PyPI فقط CPU است، و حجم پس از نصب.

**Python پیشنهادی: 3.11 یا 3.12**، به‌خاطر محدوده wheel ‏pandas 2.2.2. اگر Python کاربر 3.13 یا بالاتر باشد دو راه هست: نصب یک Python 3.12 در کنار آن (نیازمند تأیید)، یا استفاده از pandas جدیدتر با انحراف مستند از pin ‏upstream.

برآورد کل فضای لازم (تخمین، نه اندازه‌گیری):

| مورد | حجم |
|---|---|
| محیط مجازی با torch | حدود 1 تا 1.5 GB |
| وزن‌ها (small + base + tokenizer) | حدود 0.55 GB |
| clone ‏Kronos | 26 MB |
| داده BTC/USDT روزانه | کمتر از 1 MB |
| **جمع** | **حدود 2 GB از 30 GB آزاد گزارش‌شده** |

پیش از هر دانلود، حجم دقیق از سرور خوانده و با فضای آزاد واقعی مقایسه می‌شود.

## ۳. ریسک‌های سازگاری

| ریسک | توضیح | برخورد |
|---|---|---|
| GPU ‏940MX | 2 GB ‏VRAM و معماری قدیمی. احتمال دارد buildهای CUDA فعلی PyTorch این کارت را پشتیبانی نکنند (تأییدنشده). | CPU مبنا است. GPU فقط اگر probe و یک تست واقعی `torch.cuda` موفق شود؛ هیچ تغییری در درایور داده نمی‌شود. |
| سرعت CPU | i7-6500U دو هسته‌ای است. تولید خودرگرسیو است و هزینه با `pred_len × تعداد مسیر` رشد می‌کند. زمان واقعی نامعلوم است. | smoke با ۱ مسیر و افق ۷، سپس افزایش مرحله‌ای تا ۲۰. تعداد واقعی اجراشده گزارش می‌شود. |
| RAM | batch ‏۲۰تایی با context ‏400 روی base اندازه‌گیری نشده است. | اندازه‌گیری با psutil؛ در صورت نیاز تقسیم به batchهای کوچک‌تر. |
| نسخه Python | pandas 2.2.2 روی 3.13+ wheel ندارد. | بخش ۲. |
| دسترسی Binance | ممکن است در برخی شبکه‌ها محدود باشد. | در صورت خطا توقف و گزارش؛ منبع جایگزین فقط با تأیید. |
| upstream بدون بسته pip | کد باید clone و به commit ثابت pin شود. | clone در `vendor/Kronos` (خارج از Git ما) و ثبت commit. |

## ۴. طرح ارزیابی (P0.4 تا P0.6) — پیشنهاد

**داده.** BTC/USDT روزانه از endpoint عمومی `GET /api/v3/klines` بایننس، بدون credential. دانسته‌های تأییدنشده که روی پاسخ واقعی بررسی می‌شوند: کندل روزانه 00:00 UTC باز می‌شود؛ timestamp بر حسب میلی‌ثانیه UTC است؛ حداکثر 1000 کندل در هر درخواست؛ حجم بر حسب BTC و quote volume بر حسب USDT. نگاشت پیشنهادی: `volume` ← حجم پایه، `amount` ← quote volume. آخرین کندلِ هنوز بسته‌نشده حذف می‌شود. داده خام بدون تغییر و نسخه پاک‌سازی‌شده جدا ذخیره می‌شوند.

**تنظیم یکسان برای هر دو مدل.** همان سری، همان مبدأها، همان lookback (پیشنهاد: 400 کندل، زیر سقف 512)، همان `T`، `top_p`، تعداد مسیر و seed.

**ارزیابی.** چند مبدأ پیش‌بینی به ترتیب زمانی (بدون shuffle)، افق‌های ۷، ۱۴ و ۳۰ روز، مقایسه روی `close`. معیارها: MAE، RMSE، sMAPE با مخرج `(|y| + |ŷ|)/2` و مقدار صفر وقتی هر دو صفرند. baseline: آخرین close مشاهده‌شده. پوشش تجربی P10–P90 جداگانه شمرده می‌شود و ۸۰٪ فرض نمی‌شود. هیچ سیگنال خرید/فروشی تولید نمی‌شود.

**محدودیت‌هایی که از هم‌اکنون معلوم‌اند:**

- مدل‌ها zero-shot استفاده می‌شوند، پس چیزی fit نمی‌شود و نشت از طریق نرمال‌سازی وجود ندارد (نرمال‌سازی فقط روی پنجره ورودی است).
- **اما** Kronos روی داده بیش از ۴۵ صرافی آموزش دیده و تاریخ پایان داده آموزشی را نمی‌دانیم. اگر بازه آزمون ما در داده آموزشی باشد، نتایج خوش‌بینانه خواهند بود. تا روشن شدن این تاریخ، فقط مبدأهای بسیار اخیر قابل اتکاترند و این در گزارش قید می‌شود.
- مبدأهای با افق هم‌پوشان مستقل نیستند. با یک دارایی و تعداد کم مبدأ، تفاوت small و base به احتمال زیاد از نظر آماری قابل اتکا نخواهد بود؛ گزارش این را صریح می‌گوید.

## ۵. فرمان‌های پیشنهادی اولیه (نسخه به‌روز در `README.md`)

```powershell
# گام ۱ — فقط‌خواندنی، بدون نصب
py scripts\p0_env_probe.py

# گام ۲ — پس از تأیید: محیط مجازی و وابستگی‌ها (حدود 1 تا 1.5 GB)
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-p0.txt   # این فایل پس از گام ۱ ساخته می‌شود

# گام ۳ — پس از تأیید: کد Kronos (26 MB) با commit ثابت
git clone https://github.com/shiyu-coder/Kronos.git vendor\Kronos
git -C vendor\Kronos checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a

# گام ۴ — پس از بررسی مجوز و حجم واقعی: وزن‌ها (حدود 0.55 GB) و داده
# اسکریپت‌های دانلود، benchmark و ارزیابی پس از تأیید این طرح نوشته می‌شوند.
```

## ۶. تصمیم‌های لازم از کاربر

1. خروجی `py scripts\p0_env_probe.py` روی لپ‌تاپ.
2. تأیید اینکه benchmark روی لپ‌تاپ کاربر اجرا شود (sandbox به Hugging Face و Binance دسترسی ندارد و سخت‌افزار هدف هم نیست).
3. تأیید نصب محیط مجازی و دانلود حدود 2 GB، پس از بررسی مجوز وزن‌ها.
4. تأیید Binance به‌عنوان منبع داده آزمایشی.
