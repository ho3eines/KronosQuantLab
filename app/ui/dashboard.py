"""P5 dashboard (Streamlit). Display and controlled triggering only.

No forecasting, signal, backtest or accounting logic lives here: every action
calls a function in ``app.services`` / the domain modules. Start with:
    streamlit run app/ui/dashboard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app import services  # noqa: E402
from app.backtest.engine import BacktestConfig  # noqa: E402
from app.backtest.execution import Costs  # noqa: E402
from app.backtest.portfolio import PortfolioConfig  # noqa: E402
from app.core import config, timeframes  # noqa: E402
from app.core.errors import KQLError  # noqa: E402
from app.data import engine  # noqa: E402
from app.evaluation.rolling import EvalConfig  # noqa: E402
from app.forecast.registry import MODEL_NAMES, model_available  # noqa: E402
from app.forecast.service import load_forecast_quantiles, load_forecast_runs  # noqa: E402
from app.paper import simulator  # noqa: E402
from app.signals.validation import ValidationParams  # noqa: E402

st.set_page_config(page_title="Kronos Quant Lab", layout="wide")
st.markdown(
    "<style>[data-testid='stMarkdownContainer'],[data-testid='stCaptionContainer']"
    "{direction:rtl;text-align:right}</style>", unsafe_allow_html=True,
)
st.title("Kronos Quant Lab")
st.warning("محیط پژوهشی و شبیه‌سازی محلی. هیچ اتصال معاملاتی، کلید API یا سفارش واقعی در این پروژه وجود ندارد. "
           "هیچ خروجی‌ای توصیه مالی یا تضمین رفتار بازار نیست.")

conn = services.open_db()
usable = [m for m in MODEL_NAMES if model_available(m)[0]]

with st.sidebar:
    st.header("انتخاب")
    interval = st.selectbox("بازه کندل", list(timeframes.SUPPORTED_INTERVALS),
                            index=list(timeframes.SUPPORTED_INTERVALS).index(config.INTERVAL))
    status = engine.data_status(conn, interval)
    symbols = [s["symbol"] for s in status]
    symbol = st.selectbox("نماد", symbols) if symbols else None
    model = st.selectbox("مدل", usable)
    n_paths = st.number_input("تعداد مسیر (sample_count)", 2, 200,
                              min(max(config.DEFAULT_SAMPLE_COUNT, 2), 200))
    lookback = st.number_input("lookback (کندل)", 64, config.MAX_CONTEXT,
                               min(max(config.LOOKBACK, 64), config.MAX_CONTEXT))
    with st.expander("پارامترهای نمونه‌گیری مدل"):
        default_sampling = config.SamplingConfig()
        temperature = st.number_input("temperature (T)", 0.01, 5.0, float(default_sampling.temperature))
        top_p = st.number_input("top_p", 0.01, 1.0, float(default_sampling.top_p))
        top_k = st.number_input("top_k", 0, 1000, int(default_sampling.top_k))
    sampling = config.SamplingConfig(temperature=float(temperature), top_p=float(top_p), top_k=int(top_k))
    if symbol == config.SYNTHETIC_SYMBOL:
        st.error("داده ساختگی (random walk). اعداد این نماد هیچ ارتباطی با بازار واقعی ندارند.")


def guarded(label: str, fn):
    """Run a service call; show expected failures as messages instead of crashing the app."""
    try:
        with st.spinner(label):
            return fn()
    except KQLError as exc:
        st.error(f"{type(exc).__name__}: {exc}")
        return None


def candle_figure(df: pd.DataFrame, q: pd.DataFrame | None = None) -> go.Figure:
    fig = go.Figure(go.Candlestick(x=df["timestamp"], open=df["open"], high=df["high"], low=df["low"],
                                   close=df["close"], name="OHLC"))
    if q is not None and not q.empty:
        fig.add_trace(go.Scatter(x=q["ts"], y=q["p90"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=q["ts"], y=q["p10"], fill="tonexty", line=dict(width=0),
                                 fillcolor="rgba(31,119,180,0.2)", name="P10–P90 (raw)"))
        fig.add_trace(go.Scatter(x=q["ts"], y=q["p50"], line=dict(color="#1f77b4"), name="P50"))
    fig.update_layout(height=480, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
    return fig


tab_names = ["وضعیت", "داده", "پیش‌بینی", "کالیبراسیون", "اعتبارسنجی آستانه‌ها", "بک‌تست", "پرتفوی",
             "Paper", "تنظیمات", "گزارش‌های P0"]
tabs = st.tabs(tab_names)

with tabs[0]:
    st.subheader("مدل‌ها")
    model_rows = []
    for m in MODEL_NAMES:
        ok, why = model_available(m)
        key = m.removeprefix("kronos-")
        spec = config.MODELS.get(key)
        model_rows.append({"model": m, "available": ok, "detail": why,
                           "model_id": spec.repo_id if spec else "built in",
                           "tokenizer_id": spec.tokenizer_id if spec else "-"})
    st.dataframe(pd.DataFrame(model_rows), hide_index=True, width="stretch")
    st.subheader(f"داده‌های ذخیره‌شده ({interval})")
    if status:
        st.dataframe(pd.DataFrame(status), hide_index=True, width="stretch")
    else:
        st.info("پایگاه داده برای این بازه خالی است. از تب «داده» شروع کنید.")
    st.caption(f"SQLite: {config.DB_PATH} · Binance: {' → '.join(config.BINANCE_BASE_URLS)}")

with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        text = st.text_input("نمادها برای به‌روزرسانی از Binance (با فاصله)", " ".join(config.DEFAULT_SYMBOLS))
        if st.button("به‌روزرسانی داده"):
            for s in text.split():
                out = guarded(f"دریافت {s}", lambda s=s: engine.update_symbol(
                    conn, engine.BinanceProvider(interval=interval), s))
                if out:
                    st.success(f"{s}: {out['inserted']} کندل جدید، آخرین {out['last'][:10]}")
    with c2:
        st.write("بدون اینترنت: یک سری **ساختگی** برای آزمایش رابط")
        if st.button("بارگذاری داده ساختگی"):
            out = guarded("ساخت داده", lambda: engine.store_candles(
                conn, config.SYNTHETIC_SYMBOL, engine.synthetic_candles(interval=interval), "synthetic",
                interval=interval))
            if out:
                st.success(f"{out['inserted']} کندل ساختگی اضافه شد")
                st.rerun()
    if symbol:
        df = engine.load_candles(conn, symbol, interval)
        st.plotly_chart(candle_figure(df.tail(365)), width="stretch")
        st.dataframe(df.tail(10), hide_index=True, width="stretch")

with tabs[2]:
    if not symbol:
        st.info("ابتدا داده بارگذاری کنید.")
    else:
        horizon = st.slider("افقی (pred_len، کندل)", 1, config.MAX_HORIZON, min(30, config.MAX_HORIZON))
        if st.button("تولید پیش‌بینی"):
            out = guarded("اجرای مدل", lambda: services.forecast_now(
                conn, symbol, model, horizon, int(n_paths), int(lookback), interval=interval, sampling=sampling))
            if out:
                st.success(f"اجرای شماره {out[1]} ذخیره شد")
        runs = load_forecast_runs(conn, symbol, interval)
        if runs.empty:
            st.info("هنوز پیش‌بینی‌ای ذخیره نشده است.")
        else:
            run_id: int = st.selectbox("اجرا", runs["id"], format_func=lambda i: (
                f"#{i} · {runs.set_index('id').loc[i, 'model']} · {runs.set_index('id').loc[i, 'origin_ts'][:10]}"))
            q = load_forecast_quantiles(conn, int(run_id))
            st.plotly_chart(candle_figure(engine.load_candles(conn, symbol, interval).tail(180), q), width="stretch")
            st.caption("بازه P10–P90 خام است و پوشش ۸۰٪ را تضمین نمی‌کند؛ پوشش واقعی در تب «کالیبراسیون» اندازه‌گیری می‌شود.")
            st.dataframe(q, hide_index=True, width="stretch")

with tabs[3]:
    if symbol:
        c1, c2, c3 = st.columns(3)
        n_origins = c1.number_input("تعداد مبدأ", 4, 200, 16)
        level = c2.selectbox("سطح هدف پوشش", [0.8, 0.9], index=0)
        frac = c3.slider("سهم مبدأهای کالیبراسیون", 0.3, 0.8, 0.5)
        if st.button("اجرای ارزیابی و کالیبراسیون"):
            cfg = EvalConfig(lookback=int(lookback), n_origins=int(n_origins), n_paths=int(n_paths),
                             interval=interval)
            guarded("اجرای rolling", lambda: services.calibrate(conn, symbol, model, cfg, frac, level,
                                                                sampling=sampling))
    cal_runs = services.calibration_runs()
    if not cal_runs:
        st.info("هنوز کالیبراسیونی اجرا نشده است.")
    for run in cal_runs[:5]:
        with st.expander(f"{Path(run['run_dir']).name} · {run['symbol']} · {run['model']} · {run['n_origins_executed']} مبدأ"):
            st.dataframe(pd.DataFrame(run["calibration"]), hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame(run["metrics"]), hide_index=True, width="stretch")

with tabs[4]:
    st.caption("ARI بین رژیم هر کندل و رژیم «پنجره آینده» سنجیده می‌شود؛ توزیع صفر از جایگشت بازده‌ها و "
               "پایداری از بوت‌استرپ بلوکی می‌آید. گذشتن از این آزمون یعنی برچسب‌ها از تصادف جدا هستند، نه اینکه قواعد سودآورند.")
    if not symbol:
        st.info("ابتدا داده بارگذاری کنید.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        alpha = c1.number_input("validation_alpha", 0.01, 0.5, 0.05, step=0.01)
        n_perm = c2.number_input("n_permutations", 2, 1000, 100)
        n_boot = c3.number_input("n_bootstrap", 2, 1000, 50)
        forward = c4.number_input("پنجره آینده (کندل)", 2, config.MAX_HORIZON, 10)
        if st.button("کالیبراسیون آستانه‌ها"):
            params = ValidationParams(alpha=float(alpha), n_permutations=int(n_perm), n_bootstrap=int(n_boot),
                                      forward_window=int(forward), interval=interval)
            guarded("اجرای آزمون ARI", lambda: services.validate_thresholds(conn, symbol, params))
    val_runs = services.validation_runs()
    if not val_runs:
        st.info("هنوز اعتبارسنجی آستانه‌ای اجرا نشده است.")
    for run in val_runs[:5]:
        verdict = "PASSED" if run["passed"] else "NOT PASSED"
        with st.expander(f"{Path(run['run_dir']).name} · {run['symbol']} · {verdict}"):
            st.write({"observed_ari": run["observed_ari"], "thresholds": run["thresholds"],
                      "null": run["null"], "bootstrap": run["bootstrap"]})
            for warning in run["warnings"]:
                st.warning(warning)

with tabs[5]:
    st.caption("تصمیم پس از بسته‌شدن کندل t و فقط با داده تا t؛ اجرا در قیمت باز کندل t+1 با کارمزد و اسلیپیج. "
               "نتیجه بک‌تست توصیف گذشته است، نه پیش‌بینی سود.")
    if symbol:
        c1, c2, c3, c4 = st.columns(4)
        n_dec = c1.number_input("تعداد تصمیم", 2, 500, 26)
        every = c2.number_input("فاصله تصمیم (کندل)", 1, 60, 7)
        fee = c3.number_input("کارمزد (bps)", 0.0, 100.0, 10.0)
        slip = c4.number_input("اسلیپیج (bps)", 0.0, 100.0, 5.0)
        if st.button("اجرای بک‌تست"):
            def job():
                cfg = BacktestConfig(lookback=int(lookback), n_paths=int(n_paths), rebalance_every=int(every),
                                     n_decisions=int(n_dec), interval=interval,
                                     costs=Costs(fee_bps=fee, slippage_bps=slip))
                params, source = services.signal_params(symbol, model, services.backtest_start(conn, symbol, cfg),
                                                        interval=interval)
                return services.backtest(conn, symbol, model, params, cfg, source, sampling=sampling)

            done = guarded("بک‌تست", job)
            if done and done[0].errors:
                st.warning(f"{len(done[0].errors)} تصمیم ناموفق بود و «بدون اقدام» حساب شد: {done[0].errors[0]['error']}")
    bt_runs = services.backtest_runs()
    if not bt_runs:
        st.info("هنوز بک‌تستی اجرا نشده است.")
    else:
        pick = st.selectbox("اجرای بک‌تست", range(len(bt_runs)), format_func=lambda i: (
            f"{Path(bt_runs[i]['run_dir']).name} · {bt_runs[i]['symbol']} · {bt_runs[i]['model']}"))
        run = bt_runs[pick]
        if run.get("synthetic_data"):
            st.error("این بک‌تست روی داده ساختگی اجرا شده است.")
        st.dataframe(pd.DataFrame(run["metrics"]).T, width="stretch")
        st.caption(f"بازه: {run.get('interval_factor_source', '')}")
        eq = pd.read_csv(Path(run["run_dir"]) / "equity.csv")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["equity"], name="strategy"))
        fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["buy_hold"], name="buy & hold"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, width="stretch")
        dec_file = Path(run["run_dir"]) / "decisions.csv"
        if dec_file.stat().st_size > 2:
            st.dataframe(pd.read_csv(dec_file), hide_index=True, width="stretch")

with tabs[6]:
    st.caption("شبیه‌سازی سبد Qlib-style: امتیاز هر نماد = میانه بازده پیش‌بینی‌شده؛ نگهداری n_symbol_hold برتر، "
               "حذف حداکثر n_symbol_drop پس از hold_thresh کندل، اجرا در باز کندل بعد با کارمزد. فقط پژوهش.")
    if len(symbols) < 2:
        st.info("برای شبیه‌سازی پرتفوی به داده حداقل دو نماد در همین بازه نیاز است.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        picked = c1.multiselect("نمادها", symbols, default=symbols[:min(5, len(symbols))])
        n_hold = c2.number_input("n_symbol_hold", 1, max(1, len(symbols)), min(config.PORTFOLIO_DEFAULTS.n_symbol_hold, len(symbols)))
        n_drop = c3.number_input("n_symbol_drop", 1, max(1, int(n_hold)), min(config.PORTFOLIO_DEFAULTS.n_symbol_drop, int(n_hold)))
        hold = c4.number_input("hold_thresh (کندل)", 0, 200,
                               min(max(config.PORTFOLIO_DEFAULTS.hold_thresh, 0), 200))
        c5, c6, c7 = st.columns(3)
        account = c5.number_input("account", 100.0, 1e12, float(config.PORTFOLIO_DEFAULTS.account))
        hz = c6.number_input("افق امتیازدهی", 1, config.MAX_HORIZON, 7)
        every_p = c7.number_input("فاصله بازتوازن", 1, 60, 1)
        if st.button("اجرای پرتفوی"):
            if len(picked) < 2:
                st.error("حداقل دو نماد انتخاب کنید.")
            else:
                def job_p():
                    cfg = PortfolioConfig(n_symbol_hold=int(n_hold), n_symbol_drop=int(n_drop),
                                          hold_thresh=int(hold), initial_cash=float(account),
                                          lookback=int(lookback), horizon=int(hz), n_paths=int(n_paths),
                                          rebalance_every=int(every_p), interval=interval)
                    return services.portfolio_backtest(conn, picked, model, cfg, sampling=sampling)

                done_p = guarded("پرتفوی", job_p)
                if done_p:
                    st.dataframe(pd.DataFrame(done_p[1]["metrics"]).T, width="stretch")
    p_runs = services.portfolio_runs()
    if not p_runs:
        st.info("هنوز شبیه‌سازی پرتفویی اجرا نشده است.")
    else:
        pick_p = st.selectbox("اجرای پرتفوی", range(len(p_runs)), format_func=lambda i: (
            f"{Path(p_runs[i]['run_dir']).name} · {len(p_runs[i]['symbols'])} نماد"))
        run_p = p_runs[pick_p]
        if run_p.get("synthetic_data"):
            st.error("این اجرا روی داده ساختگی است.")
        st.dataframe(pd.DataFrame(run_p["metrics"]).T, width="stretch")
        eq_p = pd.read_csv(Path(run_p["run_dir"]) / "equity.csv")
        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(x=eq_p["timestamp"], y=eq_p["equity"], name="portfolio"))
        fig_p.add_trace(go.Scatter(x=eq_p["timestamp"], y=eq_p["equal_weight"], name="equal weight"))
        fig_p.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig_p, width="stretch")
        trades_file = Path(run_p["run_dir"]) / "trades.csv"
        if trades_file.stat().st_size > 2:
            st.dataframe(pd.read_csv(trades_file).tail(50), hide_index=True, width="stretch")

with tabs[7]:
    st.caption("شبیه‌ساز محلی با پول فرضی. سفارش‌ها فقط ردیف‌هایی در SQLite هستند و در قیمت باز کندل بعدی محاسبه می‌شوند.")
    has_account = conn.execute("SELECT 1 FROM paper_account").fetchone() is not None
    if not has_account:
        cash = st.number_input("موجودی فرضی اولیه", 100.0, 1e9, 10_000.0)
        if st.button("ساخت حساب شبیه‌سازی"):
            guarded("ساخت", lambda: simulator.init_account(conn, cash))
            st.rerun()
    else:
        if symbol and st.button("اجرای گام روزانه"):
            out = guarded("گام", lambda: services.paper_step(conn, symbol, model, int(n_paths), int(lookback),
                                                             interval=interval, sampling=sampling))
            if out:
                st.json(out)
        acct = guarded("وضعیت", lambda: services.paper_status(conn, interval))
        if acct:
            c1, c2, c3 = st.columns(3)
            c1.metric("ارزش کل (فرضی)", f"{acct['equity']:,.2f}", f"{acct['return']:+.2%}")
            c2.metric("نقد (فرضی)", f"{acct['cash']:,.2f}")
            c3.metric("تعداد موقعیت", len(acct["positions"]))
            if acct["positions"]:
                st.dataframe(pd.DataFrame(acct["positions"]), hide_index=True, width="stretch")
        st.subheader("سفارش‌های شبیه‌سازی‌شده")
        st.dataframe(simulator.orders_frame(conn), hide_index=True, width="stretch")
    st.subheader("Audit log")
    st.dataframe(simulator.audit_frame(conn), hide_index=True, width="stretch")

with tabs[8]:
    st.subheader("تنظیمات مؤثر (بدون هیچ راز یا کلید API)")
    st.json(config.effective_settings())
    st.subheader("بازه‌های پشتیبانی‌شده")
    st.dataframe(pd.DataFrame(timeframes.describe()), hide_index=True, width="stretch")
    st.caption("این مقادیر از متغیرهای محیطی خوانده می‌شوند؛ نمونه‌ها در .env.example آمده است.")

with tabs[9]:
    report = config.REPO_ROOT / "docs" / "P0_model_benchmark.md"
    if report.is_file():
        st.markdown(report.read_text(encoding="utf-8"))
    else:
        st.info("گزارش مقایسه small و base هنوز ساخته نشده است (benchmark واقعی اجرا نشده).")
    for d in sorted(config.REPORTS_DIR.glob("*_*"), reverse=True)[:20]:
        files = [f for f in d.glob("*.json")] if d.is_dir() else []
        for f in files:
            with st.expander(f"{d.name}/{f.name}"):
                st.json(json.loads(f.read_text(encoding="utf-8")), expanded=False)

conn.close()
