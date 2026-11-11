"""Render docs/P0_model_benchmark.md from machine-readable results. Facts only."""
from __future__ import annotations

from typing import Any


def _f(x: Any, nd: int = 2) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return str(x)


def _table(header: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_f(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render(env: dict[str, Any], manifests: dict[str, Any], bench: dict[str, Any] | None,
           evaluation: dict[str, Any] | None, metric_rows: list[dict[str, Any]]) -> str:
    L: list[str] = ["# P0 — گزارش مقایسه Kronos-small و Kronos-base", ""]
    L += ["این فایل به‌طور خودکار با `python scripts/p0.py report` از نتایج ماشینی ساخته شده است. "
          "فقط اعداد اندازه‌گیری‌شده را نشان می‌دهد؛ هیچ سیگنال خرید/فروشی در آن نیست و هیچ عددی تضمین رفتار بازار نیست.", ""]

    L += ["## ۱. محیط اجرا", "", _table(["مورد", "مقدار"], [[k, v] for k, v in env.items()]), ""]

    L += ["## ۲. مدل‌ها و checkpointها", ""]
    rows = [[k, m.get("repo_id"), m.get("resolved_sha"), m.get("license") or "اعلام‌نشده در model card",
             round((m.get("total_bytes") or 0) / 1e6, 1)] if m else [k, "manifest یافت نشد", None, None, None]
            for k, m in manifests.items()]
    L += [_table(["کلید", "مخزن", "commit", "مجوز (model card)", "حجم MB"], rows), ""]

    L += ["## ۳. Benchmark منابع و زمان", ""]
    if not bench:
        L += ["**اجرا نشده است.**", ""]
    else:
        c = bench["config"]
        L += [f"شرایط یکسان برای هر دو مدل: device درخواستی `{c['device_requested']}`، lookback={c['lookback']}، "
              f"افق={c['horizon']}، مراحل تعداد مسیر={c['stages']}، تکرار هر مرحله={c['repeats']}، "
              f"T={c['sampling']['temperature']}، top_p={c['sampling']['top_p']}، top_k={c['sampling']['top_k']}.", ""]
        rows = []
        for key, r in bench["models"].items():
            rows.append([key, r.get("status"), r.get("device"), r.get("n_parameters"), r.get("weights_mb"),
                         r.get("load_seconds"), r.get("warmup_seconds"), r.get("rss_after_load_mb"),
                         r.get("same_seed_reproducible"), f"{r.get('max_paths_executed')} از {r.get('max_paths_requested')}"])
        L += [_table(["مدل", "وضعیت", "device", "پارامتر", "حجم وزن MB", "بارگذاری s", "warm-up s",
                      "RSS پس از بارگذاری MB", "بازتولید با seed یکسان", "مسیر اجراشده از درخواستی"], rows), ""]
        rows = []
        for key, r in bench["models"].items():
            for s in r.get("stages", []):
                rows.append([key, s["n_paths"], s.get("runs_executed"), s.get("mean_seconds"), s.get("min_seconds"),
                             s.get("max_seconds"), s.get("peak_rss_mb"), s.get("mean_cpu_percent"),
                             s.get("peak_vram_mb"), s.get("error") or s.get("stopped_reason")])
        L += [_table(["مدل", "تعداد مسیر", "اجرای زمان‌گیری‌شده", "میانگین s", "کمینه s", "بیشینه s",
                      "اوج RSS MB", "CPU٪ (۱۰۰ = یک هسته منطقی)", "اوج VRAM MB", "خطا / توقف"], rows), ""]
        for key, r in bench["models"].items():
            if r.get("error"):
                L += [f"- خطای `{key}`: `{r['error']}`"]
        L += [f"- دلیل انتخاب device: {bench.get('device_reason')}", ""]
        L += ["شکل خروجی خام: `(n_paths, horizon, 6)` با ترتیب ستون‌های `open, high, low, close, volume, amount`؛ "
              "فایل‌های `raw_<model>.npy` در پوشه همان اجرا ذخیره شده‌اند.", ""]

    L += ["## ۴. کیفیت پیش‌بینی (close)", ""]
    if not evaluation:
        L += ["**اجرا نشده است.**", ""]
    else:
        c, d = evaluation["config"], evaluation["dataset"]
        L += [f"داده: `{d['file']}` ({d['rows']} کندل، {d['first']} تا {d['last']}). "
              f"lookback={c['lookback']}، تعداد مبدأ درخواستی={c['n_origins']}، فاصله مبدأها={c['stride']} کندل، "
              f"تعداد مسیر={c['n_paths']}، seed پایه={c['seed']}.", ""]
        for key, m in evaluation["models"].items():
            L += [f"- `{key}`: وضعیت {m['status']}، مبدأ اجراشده {m.get('n_origins_executed', 0)}، "
                  f"مسیر اجراشده {m.get('n_paths_executed', 0)} از {m.get('n_paths_requested', c['n_paths'])}، "
                  f"زمان کل {_f(m.get('total_seconds'))} ثانیه" + (f"، خطا: `{m['error']}`" if m.get("error") else "")]
        L += ["", "تعریف‌ها: «path» یعنی همه گام‌های ۱ تا h؛ «endpoint» یعنی فقط گام h. "
              "`p50` میانه مسیرها، `mean` میانگین مسیرها، `naive` آخرین close مشاهده‌شده. "
              "sMAPE بر حسب درصد (۰ تا ۲۰۰). پوشش، سهم مقادیر واقعی داخل بازه P10 تا P90 است و ۸۰٪ فرض نشده است.", ""]
        rows = [[r["model"], r["horizon"], r["scope"], r["forecast"], r["mae"], r["rmse"], r["smape"],
                 r["coverage_p10_p90"], r["n"]] for r in metric_rows]
        L += [_table(["مدل", "افق", "دامنه", "پیش‌بینی", "MAE", "RMSE", "sMAPE٪", "پوشش P10–P90", "n"], rows), ""]
        if evaluation.get("paired"):
            L += ["### مقایسه جفتی در گام پایانی (میانه مسیرها، مبدأهای مشترک)", ""]
            rows = [[p["horizon"], p["n_common_origins"], p["base_better_than_small"], p["small_better_than_naive"],
                     p["base_better_than_naive"], p["mean_abs_err_small"], p["mean_abs_err_base"], p["mean_abs_err_naive"]]
                    for p in evaluation["paired"]]
            L += [_table(["افق", "مبدأ مشترک", "base بهتر از small", "small بهتر از naive", "base بهتر از naive",
                          "میانگین خطای small", "میانگین خطای base", "میانگین خطای naive"], rows), ""]

    L += ["## ۵. محدودیت‌های تفسیر", "",
          "- یک دارایی و تعداد کمی مبدأ: تفاوت‌های کوچک بین small و base از نظر آماری قابل اتکا نیستند.",
          "- تاریخ پایان داده آموزشی Kronos معلوم نیست؛ اگر بازه آزمون در داده آموزشی بوده باشد نتایج خوش‌بینانه‌اند.",
          "- با تعداد مسیر کم، P10 و P90 برآوردهای پرنویزی هستند.",
          "- زمان‌ها فقط برای همین سخت‌افزار و همین نسخه‌ها معتبرند.", "",
          "## ۶. پیشنهاد فنی", "",
          "پس از بازبینی این اعداد نوشته می‌شود؛ تولید خودکار ندارد تا نتیجه‌ای بدون بررسی اعلام نشود.", ""]
    return "\n".join(L)
