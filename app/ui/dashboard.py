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
from app.core import config  # noqa: E402
from app.core.errors import KQLError  # noqa: E402
from app.data import engine  # noqa: E402
from app.evaluation.rolling import EvalConfig  # noqa: E402
from app.forecast.registry import MODEL_NAMES, model_available  # noqa: E402
from app.forecast.service import load_forecast_quantiles, load_forecast_runs  # noqa: E402
from app.paper import simulator  # noqa: E402

st.set_page_config(page_title="Kronos Quant Lab", layout="wide")
st.markdown(
    "<style>[data-testid='stMarkdownContainer'],[data-testid='stCaptionContainer']"
    "{direction:rtl;text-align:right}</style>", unsafe_allow_html=True,
)
st.title("Kronos Quant Lab")
st.warning("محیط پژوهشی و شبیه‌سازی محلی. هیچ اتصال معاملاتی، کلید API یا سفارش واقعی در این پروژه وجود ندارد. "
           "هیچ خروجی‌ای توصیه مالی یا تضمین رفتار بازار نیست.")

conn = services.open_db()
status = engine.data_status(conn)
symbols = [s["symbol"] for s in status]
usable = [m for m in MODEL_NAMES if model_available(m)[0]]

with st.sidebar:
    st.header("انتخاب")
    symbol = st.selectbox("نماد", symbols) if symbols else None
    model = st.selectbox("مدل", usable)
    n_paths = st.number_input("تعداد مسیر", 2, 200, 20)
    lookback = st.number_input("lookback (کندل)", 64, config.MAX_CONTEXT, 400)
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


tabs = st.tabs(["وضعیت", "داده", "پیش‌بینی", "کالیبراسیون", "بک‌تست", "Paper", "گزارش‌های P0"])

with tabs[0]:
    st.subheader("مدل‌ها")
    st.dataframe(pd.DataFrame([{"model": m, "available": model_available(m)[0], "detail": model_available(m)[1]}
                               for m in MODEL_NAMES]), hide_index=True, width="stretch")
    st.subheader("داده‌های ذخیره‌شده")
    if status:
        st.dataframe(pd.DataFrame(status), hide_index=True, width="stretch")
    else:
        st.info("پایگاه داده خالی است. از تب «داده» شروع کنید.")
    st.caption(f"SQLite: {config.DB_PATH}")

with tabs[1]:
    c1, c2 = st.columns(2)
    with c1:
        text = st.text_input("نمادها برای به‌روزرسانی از Binance (با فاصله)", " ".join(config.DEFAULT_SYMBOLS))
        if st.button("به‌روزرسانی داده"):
            for s in text.split():
                out = guarded(f"دریافت {s}", lambda s=s: engine.update_symbol(conn, engine.BinanceProvider(), s))
                if out:
                    st.success(f"{s}: {out['inserted']} کندل جدید، آخرین {out['last'][:10]}")
    with c2:
        st.write("بدون اینترنت: یک سری **ساختگی** برای آزمایش رابط")
        if st.button("بارگذاری داده ساختگی"):
            out = guarded("ساخت داده", lambda: engine.store_candles(
                conn, config.SYNTHETIC_SYMBOL, engine.synthetic_candles(), "synthetic"))
            if out:
                st.success(f"{out['inserted']} کندل ساختگی اضافه شد")
                st.rerun()
    if symbol:
        df = engine.load_candles(conn, symbol)
        st.plotly_chart(candle_figure(df.tail(365)), width="stretch")
        st.dataframe(df.tail(10), hide_index=True, width="stretch")

with tabs[2]:
    if not symbol:
        st.info("ابتدا داده بارگذاری کنید.")
    else:
        horizon = st.slider("افق (روز)", 1, 60, 30)
        if st.button("تولید پیش‌بینی"):
            out = guarded("اجرای مدل", lambda: services.forecast_now(conn, symbol, model, horizon, int(n_paths), int(lookback)))
            if out:
                st.success(f"اجرای شماره {out[1]} ذخیره شد")
        runs = load_forecast_runs(conn, symbol)
        if runs.empty:
            st.info("هنوز پیش‌بینی‌ای ذخیره نشده است.")
        else:
            run_id = st.selectbox("اجرا", runs["id"], format_func=lambda i: (
                f"#{i} · {runs.set_index('id').loc[i, 'model']} · {runs.set_index('id').loc[i, 'origin_ts'][:10]}"))
            q = load_forecast_quantiles(conn, int(run_id))
            st.plotly_chart(candle_figure(engine.load_candles(conn, symbol).tail(180), q), width="stretch")
            st.caption("بازه P10–P90 خام است و پوشش ۸۰٪ را تضمین نمی‌کند؛ پوشش واقعی در تب «کالیبراسیون» اندازه‌گیری می‌شود.")
            st.dataframe(q, hide_index=True, width="stretch")

with tabs[3]:
    if symbol:
        c1, c2, c3 = st.columns(3)
        n_origins = c1.number_input("تعداد مبدأ", 4, 200, 16)
        level = c2.selectbox("سطح هدف پوشش", [0.8, 0.9], index=0)
        frac = c3.slider("سهم مبدأهای کالیبراسیون", 0.3, 0.8, 0.5)
        if st.button("اجرای ارزیابی و کالیبراسیون"):
            cfg = EvalConfig(lookback=int(lookback), n_origins=int(n_origins), n_paths=int(n_paths))
            guarded("اجرای rolling", lambda: services.calibrate(conn, symbol, model, cfg, frac, level))
    runs = services.calibration_runs()
    if not runs:
        st.info("هنوز کالیبراسیونی اجرا نشده است.")
    for run in runs[:5]:
        with st.expander(f"{Path(run['run_dir']).name} · {run['symbol']} · {run['model']} · {run['n_origins_executed']} مبدأ"):
            st.dataframe(pd.DataFrame(run["calibration"]), hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame(run["metrics"]), hide_index=True, width="stretch")

with tabs[4]:
    st.caption("تصمیم پس از بسته‌شدن کندل t و فقط با داده تا t؛ اجرا در قیمت باز کندل t+1 با کارمزد و اسلیپیج. "
               "نتیجه بک‌تست توصیف گذشته است، نه پیش‌بینی سود.")
    if symbol:
        c1, c2, c3, c4 = st.columns(4)
        n_dec = c1.number_input("تعداد تصمیم", 2, 500, 26)
        every = c2.number_input("فاصله تصمیم (کندل)", 1, 60, 7)
        fee = c3.number_input("کارمزد (bps)", 0.0, 100.0, 10.0)
        slip = c4.number_input("اسلیپیج (bps)", 0.0, 100.0, 5.0)
        if st.button("اجرای بک‌تست"):
            params, source = services.signal_params(symbol, model)
            cfg = BacktestConfig(lookback=int(lookback), n_paths=int(n_paths), rebalance_every=int(every),
                                 n_decisions=int(n_dec), costs=Costs(fee_bps=fee, slippage_bps=slip))
            guarded("بک‌تست", lambda: services.backtest(conn, symbol, model, params, cfg, source))
    runs = services.backtest_runs()
    if not runs:
        st.info("هنوز بک‌تستی اجرا نشده است.")
    else:
        pick = st.selectbox("اجرای بک‌تست", range(len(runs)), format_func=lambda i: (
            f"{Path(runs[i]['run_dir']).name} · {runs[i]['symbol']} · {runs[i]['model']}"))
        run = runs[pick]
        if run.get("synthetic_data"):
            st.error("این بک‌تست روی داده ساختگی اجرا شده است.")
        st.dataframe(pd.DataFrame(run["metrics"]).T, width="stretch")
        eq = pd.read_csv(Path(run["run_dir"]) / "equity.csv")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["equity"], name="strategy"))
        fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["buy_hold"], name="buy & hold"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, width="stretch")
        dec_file = Path(run["run_dir"]) / "decisions.csv"
        if dec_file.stat().st_size > 2:
            st.dataframe(pd.read_csv(dec_file), hide_index=True, width="stretch")

with tabs[5]:
    st.caption("شبیه‌ساز محلی با پول فرضی. سفارش‌ها فقط ردیف‌هایی در SQLite هستند و در قیمت باز کندل بعدی محاسبه می‌شوند.")
    has_account = conn.execute("SELECT 1 FROM paper_account").fetchone() is not None
    if not has_account:
        cash = st.number_input("موجودی فرضی اولیه", 100.0, 1e9, 10_000.0)
        if st.button("ساخت حساب شبیه‌سازی"):
            guarded("ساخت", lambda: simulator.init_account(conn, cash))
            st.rerun()
    else:
        if symbol and st.button("اجرای گام روزانه"):
            out = guarded("گام", lambda: services.paper_step(conn, symbol, model, int(n_paths), int(lookback)))
            if out:
                st.json(out)
        acct = guarded("وضعیت", lambda: services.paper_status(conn))
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

with tabs[6]:
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
