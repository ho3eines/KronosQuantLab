"""Kronos Quant Lab - main command line (P1..P5). Research and local simulation only.

  python scripts/kql.py settings                                  effective configuration (no secrets)
  python scripts/kql.py data update [--symbols BTCUSDT ETHUSDT] [--interval 1d]
  python scripts/kql.py data demo [--rows 900] [--interval 1d]    load a SYNTHETIC series (no internet)
  python scripts/kql.py data import --symbol X --csv file.csv     import a clean CSV or an MT5 export
  python scripts/kql.py data venues                               which venues exist and how they connect
  python scripts/kql.py data status [--interval 1d]
  python scripts/kql.py models                                    which forecasters are usable, and their IDs
  python scripts/kql.py forecast  --symbol S --model M            P10/P50/P90 forecast, stored in SQLite
  python scripts/kql.py calibrate --symbol S --model M            rolling accuracy + interval calibration
  python scripts/kql.py validate  --symbol S                      P3 threshold calibration (ARI null + bootstrap)
  python scripts/kql.py backtest  --symbol S --model M            walk-forward backtest with costs
  python scripts/kql.py portfolio --symbols A B C --model M       Qlib-style TopkDropout portfolio backtest
  python scripts/kql.py paper init | step | status                local paper simulator
  python scripts/kql.py ui                                        how to start the dashboard

Models: baseline-bootstrap (built in), kronos-small, kronos-base (need downloaded weights).
Market data: data-api.binance.vision first, api.binance.com automatically on HTTP 451/403.
Venues: Binance (bare symbols), NOBITEX:BTCIRT (public OHLC, no token), ALPARI:EURUSD (MT5 CSV export).
Everything is read-only market data: no exchange account, no API key, no order code.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from app import services  # noqa: E402
from app.backtest.engine import BacktestConfig  # noqa: E402
from app.backtest.execution import Costs  # noqa: E402
from app.backtest.portfolio import PortfolioConfig  # noqa: E402
from app.core import config, timeframes, venues  # noqa: E402
from app.core.errors import KQLError  # noqa: E402
from app.core.runs import dumps, safe_console  # noqa: E402
from app.data import alpari, engine  # noqa: E402
from app.evaluation.rolling import EvalConfig  # noqa: E402
from app.forecast.registry import BASELINE, MODEL_NAMES, model_available  # noqa: E402
from app.paper import simulator  # noqa: E402
from app.signals.validation import ValidationParams  # noqa: E402

log = logging.getLogger("kql")
DISCLAIMER = "Research output only - not a trading signal, not financial advice, no real orders exist in this project."


def _show(obj: object) -> None:
    print(dumps(obj))


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text}")
    return value


def non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative, got {text}")
    return value


def positive_float(text: str) -> float:
    value = float(text)
    if not (math.isfinite(value) and value > 0):
        raise argparse.ArgumentTypeError(f"must be a positive number, got {text}")
    return value


def probability(text: str) -> float:
    value = float(text)
    if not (math.isfinite(value) and 0 < value <= 1):
        raise argparse.ArgumentTypeError(f"must be in (0, 1], got {text}")
    return value


def alpha_value(text: str) -> float:
    value = float(text)
    if not (math.isfinite(value) and 0 < value < 1):
        raise argparse.ArgumentTypeError(f"must be strictly between 0 and 1, got {text}")
    return value


def path_count(text: str) -> int:
    value = int(text)
    if value < 2:
        raise argparse.ArgumentTypeError("at least 2 sample paths are needed for quantiles")
    return value


def lookback_count(text: str) -> int:
    value = positive_int(text)
    if value > config.MAX_CONTEXT:
        raise argparse.ArgumentTypeError(f"lookback cannot exceed {config.MAX_CONTEXT} bars")
    return value


def horizon_count(text: str) -> int:
    value = positive_int(text)
    if value > config.MAX_HORIZON:
        raise argparse.ArgumentTypeError(f"horizon cannot exceed MAX_HORIZON={config.MAX_HORIZON} bars")
    return value


def interval_value(text: str) -> str:
    try:
        return timeframes.normalize(text)
    except KQLError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _sampling(args: argparse.Namespace) -> config.SamplingConfig:
    return config.SamplingConfig(temperature=args.temperature, top_k=args.top_k, top_p=args.top_p)


def cmd_settings(args: argparse.Namespace) -> int:
    settings = config.effective_settings()
    settings["timeframes"] = timeframes.describe()
    _show(settings)
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    conn = services.open_db()
    interval = args.interval
    if args.action == "update":
        failed = 0
        for symbol in args.symbols:
            try:
                provider = engine.provider_for(symbol, interval=interval)
                out = engine.update_symbol(conn, provider, symbol)
                served_by = getattr(provider, "last_base_url", None) or getattr(provider, "base_url", None)
                out["served_by"] = served_by
                notes = getattr(provider, "notes", None)
                if notes:
                    out["notes"] = notes
                _show(out)
            except KQLError as exc:  # one symbol failing must not stop the others
                failed += 1
                log.error("%s: %s", symbol, exc)
        return 1 if failed else 0
    if args.action == "demo":
        _show(engine.store_candles(conn, config.SYNTHETIC_SYMBOL, engine.synthetic_candles(args.rows, interval=interval),
                                   "synthetic", interval=interval))
        print(f"\n{config.SYNTHETIC_SYMBOL} is a generated random walk, NOT market data.")
        return 0
    if args.action == "import":
        if not args.symbol or not args.csv:
            raise KQLError("data import needs --symbol and --csv")
        path = Path(args.csv)
        fmt = args.format
        if fmt == "auto":
            fmt = "mt5" if alpari.looks_like_mt5(path) or venues.venue_name(args.symbol) == "alpari" else "csv"
        meta: dict[str, object] = {}
        if fmt == "mt5":
            df, meta = alpari.read_mt5_csv(path, interval=interval, tz_offset_hours=args.tz_offset)
        else:
            df = pd.read_csv(path)
        out = engine.store_candles(conn, args.symbol, df, f"{fmt}:{path.name}", interval=interval,
                                   strict=True if args.strict else None)
        if meta:
            out["import"] = meta
        _show(out)
        return 0
    if args.action == "venues":
        print(pd.DataFrame(venues.describe()).to_string(index=False))
        print(f"\nNobitex base URL: {config.NOBITEX_BASE_URL} (public OHLC, no token)")
        print("Alpari: no public market-data API - export from MT5 and use 'data import --format mt5'.")
        print("This project sends no orders and stores no credentials.")
        return 0
    rows = engine.data_status(conn, interval)
    print(pd.DataFrame(rows).to_string(index=False) if rows else f"database has no {interval} candles")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    for name in MODEL_NAMES:
        ok, why = model_available(name)
        print(f"{name:20s} {'available' if ok else 'NOT available'}  ({why})")
        key = name.removeprefix("kronos-")
        if key in config.MODELS:
            spec = config.MODELS[key]
            print(f"{'':20s} model_id={spec.repo_id}  tokenizer_id={spec.tokenizer_id}  "
                  f"params~{spec.parameters}  context={spec.context_length}")
    sampling = config.SamplingConfig()
    print(f"\nsampling defaults: sample_count={config.DEFAULT_SAMPLE_COUNT} "
          f"temperature={sampling.temperature} top_p={sampling.top_p} top_k={sampling.top_k}")
    print(f"window defaults: lookback={config.LOOKBACK} (max {config.MAX_CONTEXT}), "
          f"pred_len={config.DEFAULT_PRED_LEN} (max {config.MAX_HORIZON}), interval={config.INTERVAL}")
    print("market data hosts: " + " -> ".join(config.BINANCE_BASE_URLS))
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    conn = services.open_db()
    fc, run_id = services.forecast_now(conn, args.symbol, args.model, args.horizon, args.n_paths, args.lookback,
                                       args.device, interval=args.interval, sampling=_sampling(args))
    stamp_col = fc.future_ts.dt.date if args.interval == "1d" else fc.future_ts.dt.strftime("%Y-%m-%d %H:%M")
    table = pd.DataFrame({"timestamp": stamp_col, "p10": fc.p10, "p50": fc.p50, "p90": fc.p90})
    print(f"run {run_id}: {args.model} on {args.symbol} ({args.interval}), last bar {fc.origin_ts.date()}, "
          f"last close {fc.last_close:,.2f}, {fc.paths.shape[0]} sample paths, lookback {fc.lookback} "
          f"(raw, uncalibrated band)\n")
    print(table.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print("\n" + DISCLAIMER)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    conn = services.open_db()
    cfg = EvalConfig(lookback=args.lookback, horizons=tuple(args.horizons), n_origins=args.n_origins,
                     stride=args.stride or max(args.horizons), n_paths=args.n_paths, interval=args.interval)
    out = services.calibrate(conn, args.symbol, args.model, cfg, args.calib_fraction, args.level, args.device,
                             sampling=_sampling(args))
    print(pd.DataFrame(out["calibration"]).to_string(index=False))
    m = pd.DataFrame(out["metrics"])
    if not m.empty:
        print("\n" + m[m.scope == "endpoint"].to_string(index=False))
    print(f"\norigins executed: {out['n_origins_executed']} of {cfg.n_origins} requested; saved: {out['run_dir']}")
    if any(r["factor"] is None for r in out["calibration"]):
        print("factor = None: too few calibration origins for this level; the raw band stays in use.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    conn = services.open_db()
    params = ValidationParams(
        alpha=args.alpha, null_ari_max=args.null_ari_max, stability_threshold=args.stability_threshold,
        n_permutations=args.n_permutations, n_bootstrap=args.n_bootstrap, seed=args.seed,
        forward_window=args.forward_window, interval=args.interval,
    )
    out = services.validate_thresholds(conn, args.symbol, params)
    t = out["thresholds"]
    print(f"threshold calibration - {args.symbol} ({args.interval}), {out['n_bars']} bars, "
          f"{out['n_labelled_bars']} comparable\n")
    print(f"observed persistence ARI      {out['observed_ari']:+.4f}")
    print(f"null ARI (n={out['null']['n']}) mean / {100 * (1 - args.alpha):.1f}% bound   "
          f"{out['null']['ari_mean']:+.4f} / {t['null_ari_max']:+.4f}")
    print(f"bootstrap ARI (n={out['bootstrap']['n']}) median / 5%     "
          f"{out['bootstrap']['ari_median']:+.4f} / {out['bootstrap']['ari_p05']:+.4f}")
    print(f"thresholds: null_ari_max={t['null_ari_max']:.4f} (auto={t['null_ari_max_auto']}), "
          f"stability_threshold={t['stability_threshold']:.4f} (auto={t['stability_threshold_auto']})")
    print(f"\nresult: {'PASSED - labels are more persistent than chance and stable' if out['passed'] else 'NOT PASSED'}")
    for warning in out["warnings"]:
        print(f"WARNING: {warning}")
    print(f"saved: {out['run_dir']}\n{DISCLAIMER}")
    return 0 if out["passed"] else 1


def _costs(args: argparse.Namespace) -> Costs:
    return Costs(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)


def cmd_backtest(args: argparse.Namespace) -> int:
    conn = services.open_db()
    cfg = BacktestConfig(lookback=args.lookback, n_paths=args.n_paths, rebalance_every=args.rebalance_every,
                         n_decisions=args.n_decisions, initial_cash=args.cash, interval=args.interval,
                         costs=_costs(args))
    params, source = services.signal_params(args.symbol, args.model, services.backtest_start(conn, args.symbol, cfg),
                                            interval=args.interval, horizon=args.horizon, min_edge=args.min_edge)
    res, summary = services.backtest(conn, args.symbol, args.model, params, cfg, source, args.device,
                                     sampling=_sampling(args))
    print(pd.DataFrame(summary["metrics"]).T.to_string(float_format=lambda v: f"{v:,.4f}"))
    print(f"\nperiod {summary['period'][0][:10]} .. {summary['period'][1][:10]}; interval factor "
          f"{params.interval_factor:.3f} ({source}); saved: {summary['run_dir']}")
    if summary["synthetic_data"]:
        print("SYNTHETIC DATA: these numbers say nothing about any real market.")
    print(summary["disclaimer"])
    if res.errors:
        print(f"WARNING: {len(res.errors)} of {len(res.errors) + len(res.decisions)} decisions failed "
              f"(first: {res.errors[0]['error']}). Failed decisions were treated as 'do nothing'.")
        return 1
    return 0


def cmd_portfolio(args: argparse.Namespace) -> int:
    conn = services.open_db()
    symbols = list(dict.fromkeys(args.symbols))
    start, end = args.start, args.end
    if args.time_range is not None:
        if start is not None or end is not None:
            raise KQLError("use either --time-range or --start/--end, not both")
        start, end = args.time_range
    cfg = PortfolioConfig(
        n_symbol_hold=args.n_symbol_hold, n_symbol_drop=args.n_symbol_drop, hold_thresh=args.hold_thresh,
        initial_cash=args.account, lookback=args.lookback, horizon=args.horizon, n_paths=args.n_paths,
        rebalance_every=args.rebalance_every, interval=args.interval, time_range=(start, end),
        seed=args.seed, costs=_costs(args),
    )
    res, summary = services.portfolio_backtest(conn, symbols, args.model, cfg, args.device,
                                               sampling=_sampling(args))
    print(pd.DataFrame(summary["metrics"]).T.to_string(float_format=lambda v: f"{v:,.4f}"))
    print(f"\nperiod {summary['period'][0][:10]} .. {summary['period'][1][:10]}; symbols {len(symbols)}; "
          f"effective hold {res.effective_hold}; saved: {summary['run_dir']}")
    print("selection: score = median forecast return over the horizon; hold top "
          f"{cfg.n_symbol_hold}, drop at most {cfg.n_symbol_drop} after {cfg.hold_thresh} bars; "
          "execute at the next open with costs.")
    if summary["synthetic_data"]:
        print("SYNTHETIC DATA: these numbers say nothing about any real market.")
    if res.effective_hold < cfg.n_symbol_hold:
        print(f"NOTE: only {res.effective_hold} symbols were available; n_symbol_hold was clipped for this run.")
    print(summary["disclaimer"])
    if res.errors:
        print(f"WARNING: {len(res.errors)} symbol forecasts failed (first: {res.errors[0]['error']}). "
              "A failed score is skipped, never guessed.")
        return 1
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    conn = services.open_db()
    if args.action == "init":
        simulator.init_account(conn, args.cash)
        print(f"paper account created with {args.cash:,.2f} of SIMULATED money")
    elif args.action == "step":
        _show(services.paper_step(conn, args.symbol, args.model, args.n_paths, args.lookback, args.device,
                                  interval=args.interval, sampling=_sampling(args)))
    else:
        _show(services.paper_status(conn, args.interval))
        orders = simulator.orders_frame(conn)
        if not orders.empty:
            print(orders.head(15).to_string(index=False))
    print("\nLocal simulation only. No exchange is contacted and no real order can be placed by this project.")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    print("pip install -r requirements-ui.txt\nstreamlit run app/ui/dashboard.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def sampling(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--n-paths", "--sample-count", dest="n_paths", type=path_count,
                        default=config.DEFAULT_SAMPLE_COUNT,
                        help="number of sampled paths (sample_count); more = better uncertainty estimate")
        sp.add_argument("--temperature", type=positive_float, default=config.SamplingConfig().temperature,
                        help="sampling temperature T: higher = bolder paths, lower = more conservative")
        sp.add_argument("--top-p", type=probability, default=config.SamplingConfig().top_p,
                        help="nucleus-sampling probability mass")
        sp.add_argument("--top-k", type=non_negative_int, default=config.SamplingConfig().top_k,
                        help="top-k sampling cut (0 = disabled)")

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--symbol", default=config.DEFAULT_SYMBOLS[0])
        sp.add_argument("--model", choices=MODEL_NAMES, default=BASELINE)
        sp.add_argument("--device", choices=["cpu", "auto"], default="cpu")
        sp.add_argument("--interval", type=interval_value, default=config.INTERVAL,
                        choices=timeframes.SUPPORTED_INTERVALS)
        sp.add_argument("--lookback", type=lookback_count, default=config.LOOKBACK,
                        help=f"model context bars (max {config.MAX_CONTEXT})")
        sampling(sp)

    sub.add_parser("settings").set_defaults(func=cmd_settings)

    sp = sub.add_parser("data")
    sp.add_argument("action", choices=["update", "demo", "import", "venues", "status"])
    sp.add_argument("--symbols", nargs="+", default=list(config.DEFAULT_SYMBOLS))
    sp.add_argument("--symbol")
    sp.add_argument("--csv")
    sp.add_argument("--format", choices=["auto", "csv", "mt5"], default="auto",
                    help="import format; 'mt5' reads an Alpari MetaTrader 5 history export")
    sp.add_argument("--tz-offset", type=float, default=0.0,
                    help="hours to subtract from MT5 export timestamps (broker server time -> UTC)")
    sp.add_argument("--strict", action="store_true",
                    help="reject off-grid bars and calendar gaps even for venue-native venues")
    sp.add_argument("--rows", type=positive_int, default=900)
    sp.add_argument("--interval", type=interval_value, default=config.INTERVAL,
                    choices=timeframes.SUPPORTED_INTERVALS)
    sp.set_defaults(func=cmd_data)

    sub.add_parser("models").set_defaults(func=cmd_models)

    sp = sub.add_parser("forecast")
    common(sp)
    sp.add_argument("--horizon", "--pred-len", dest="horizon", type=horizon_count,
                    default=config.DEFAULT_PRED_LEN, help=f"pred_len: forecast bars (max {config.MAX_HORIZON})")
    sp.set_defaults(func=cmd_forecast)

    sp = sub.add_parser("calibrate")
    common(sp)
    sp.add_argument("--horizons", type=horizon_count, nargs="+", default=[7, 14, 30])
    sp.add_argument("--n-origins", type=positive_int, default=16)
    sp.add_argument("--stride", type=positive_int, default=None)
    sp.add_argument("--calib-fraction", type=float, default=0.5)
    sp.add_argument("--level", type=float, default=0.8)
    sp.set_defaults(func=cmd_calibrate)

    sp = sub.add_parser("validate")
    sp.add_argument("--symbol", default=config.DEFAULT_SYMBOLS[0])
    sp.add_argument("--interval", type=interval_value, default=config.INTERVAL,
                    choices=timeframes.SUPPORTED_INTERVALS)
    sp.add_argument("--alpha", type=alpha_value, default=config.VALIDATION_ALPHA,
                    help="validation_alpha: significance level of the null ARI bound")
    sp.add_argument("--null-ari-max", type=float, default=config.VALIDATION_NULL_ARI_MAX,
                    help="validation_null_ari_max: maximum ARI under the null; default: calibrated")
    sp.add_argument("--stability-threshold", type=float, default=config.VALIDATION_STABILITY_THRESHOLD,
                    help="validation_stability_threshold: minimum ARI for the stability test")
    sp.add_argument("--n-permutations", type=positive_int, default=config.N_PERMUTATIONS)
    sp.add_argument("--n-bootstrap", type=positive_int, default=config.N_BOOTSTRAP)
    sp.add_argument("--forward-window", type=positive_int, default=10,
                    help=f"bars in the forward regime window (max {config.MAX_HORIZON})")
    sp.add_argument("--seed", type=int, default=20260101)
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("backtest")
    common(sp)
    sp.add_argument("--horizon", type=horizon_count, default=7)
    sp.add_argument("--min-edge", type=float, default=0.02)
    sp.add_argument("--rebalance-every", type=positive_int, default=7)
    sp.add_argument("--n-decisions", type=positive_int, default=26)
    sp.add_argument("--cash", type=float, default=10_000.0)
    sp.add_argument("--fee-bps", type=float, default=10.0)
    sp.add_argument("--slippage-bps", type=float, default=5.0)
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("portfolio")
    sp.add_argument("--symbols", nargs="+", required=True, help="at least two stored symbols")
    sp.add_argument("--model", choices=MODEL_NAMES, default=BASELINE)
    sp.add_argument("--device", choices=["cpu", "auto"], default="cpu")
    sp.add_argument("--interval", type=interval_value, default=config.INTERVAL,
                    choices=timeframes.SUPPORTED_INTERVALS)
    sp.add_argument("--lookback", type=lookback_count, default=config.LOOKBACK)
    sp.add_argument("--horizon", type=horizon_count, default=7)
    sp.add_argument("--n-symbol-hold", "--backtest-n-symbol-hold", dest="n_symbol_hold", type=positive_int,
                    default=config.PORTFOLIO_DEFAULTS.n_symbol_hold)
    sp.add_argument("--n-symbol-drop", "--backtest-n-symbol-drop", dest="n_symbol_drop", type=positive_int,
                    default=config.PORTFOLIO_DEFAULTS.n_symbol_drop)
    sp.add_argument("--hold-thresh", "--backtest-hold-thresh", dest="hold_thresh", type=non_negative_int,
                    default=config.PORTFOLIO_DEFAULTS.hold_thresh)
    sp.add_argument("--account", type=positive_float, default=config.PORTFOLIO_DEFAULTS.account,
                    help="initial portfolio value")
    sp.add_argument("--start", default=None, help="first execution date (YYYY-MM-DD); history before it is used")
    sp.add_argument("--end", default=None, help="last date of the simulation (YYYY-MM-DD)")
    sp.add_argument("--time-range", nargs=2, metavar=("START", "END"), default=None,
                    help="backtest_time_range as two dates; same as --start/--end")
    sp.add_argument("--rebalance-every", type=positive_int, default=1)
    sp.add_argument("--seed", type=int, default=20260101)
    sp.add_argument("--fee-bps", type=float, default=10.0)
    sp.add_argument("--slippage-bps", type=float, default=5.0)
    sampling(sp)
    sp.set_defaults(func=cmd_portfolio)

    sp = sub.add_parser("paper")
    sp.add_argument("action", choices=["init", "step", "status"])
    common(sp)
    sp.add_argument("--cash", type=float, default=10_000.0)
    sp.set_defaults(func=cmd_paper)

    sub.add_parser("ui").set_defaults(func=cmd_ui)
    return p


def main(argv: list[str] | None = None) -> int:
    safe_console()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return int(args.func(args))
    except KQLError as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 2
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        log.error("file problem - %s: %s", type(exc).__name__, exc)  # missing / unreadable / malformed file
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
