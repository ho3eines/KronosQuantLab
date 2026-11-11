"""Kronos Quant Lab - main command line (P1..P5). Research and local simulation only.

  python scripts/kql.py data update [--symbols BTCUSDT ETHUSDT]   fetch new daily candles into SQLite
  python scripts/kql.py data demo                                 load a SYNTHETIC series (no internet needed)
  python scripts/kql.py data import --symbol X --csv file.csv     import a clean CSV
  python scripts/kql.py data status
  python scripts/kql.py models                                    which forecasters are usable
  python scripts/kql.py forecast  --symbol S --model M            P10/P50/P90 forecast, stored in SQLite
  python scripts/kql.py calibrate --symbol S --model M            rolling accuracy + interval calibration
  python scripts/kql.py backtest  --symbol S --model M            walk-forward backtest with costs
  python scripts/kql.py paper init | step | status                local paper simulator
  python scripts/kql.py ui                                        how to start the dashboard

Models: baseline-bootstrap (built in), kronos-small, kronos-base (need downloaded weights).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from app import services  # noqa: E402
from app.backtest.engine import BacktestConfig  # noqa: E402
from app.backtest.execution import Costs  # noqa: E402
from app.core import config  # noqa: E402
from app.core.errors import KQLError  # noqa: E402
from app.core.runs import dumps, safe_console  # noqa: E402
from app.data import engine  # noqa: E402
from app.evaluation.rolling import EvalConfig  # noqa: E402
from app.forecast.registry import BASELINE, MODEL_NAMES, model_available  # noqa: E402
from app.paper import simulator  # noqa: E402

log = logging.getLogger("kql")
DISCLAIMER = "Research output only - not a trading signal, not financial advice, no real orders exist in this project."


def _show(obj: object) -> None:
    print(dumps(obj))


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text}")
    return value


def path_count(text: str) -> int:
    value = int(text)
    if value < 2:
        raise argparse.ArgumentTypeError("at least 2 sample paths are needed for quantiles")
    return value


def cmd_data(args: argparse.Namespace) -> int:
    conn = services.open_db()
    if args.action == "update":
        provider = engine.BinanceProvider()
        failed = 0
        for symbol in args.symbols:
            try:
                _show(engine.update_symbol(conn, provider, symbol))
            except KQLError as exc:  # one symbol failing must not stop the others
                failed += 1
                log.error("%s: %s", symbol, exc)
        return 1 if failed else 0
    if args.action == "demo":
        _show(engine.store_candles(conn, config.SYNTHETIC_SYMBOL, engine.synthetic_candles(args.rows), "synthetic"))
        print(f"\n{config.SYNTHETIC_SYMBOL} is a generated random walk, NOT market data.")
        return 0
    if args.action == "import":
        if not args.symbol or not args.csv:
            raise KQLError("data import needs --symbol and --csv")
        _show(engine.store_candles(conn, args.symbol, pd.read_csv(args.csv), f"csv:{Path(args.csv).name}"))
        return 0
    rows = engine.data_status(conn)
    print(pd.DataFrame(rows).to_string(index=False) if rows else "database is empty")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    for name in MODEL_NAMES:
        ok, why = model_available(name)
        print(f"{name:20s} {'available' if ok else 'NOT available'}  ({why})")
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    conn = services.open_db()
    fc, run_id = services.forecast_now(conn, args.symbol, args.model, args.horizon, args.n_paths, args.lookback, args.device)
    table = pd.DataFrame({"date": fc.future_ts.dt.date, "p10": fc.p10, "p50": fc.p50, "p90": fc.p90})
    print(f"run {run_id}: {args.model} on {args.symbol}, last bar {fc.origin_ts.date()}, last close {fc.last_close:,.2f}, "
          f"{fc.paths.shape[0]} paths (raw, uncalibrated band)\n")
    print(table.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print("\n" + DISCLAIMER)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    conn = services.open_db()
    cfg = EvalConfig(lookback=args.lookback, horizons=tuple(args.horizons), n_origins=args.n_origins,
                     stride=args.stride or max(args.horizons), n_paths=args.n_paths)
    out = services.calibrate(conn, args.symbol, args.model, cfg, args.calib_fraction, args.level, args.device)
    print(pd.DataFrame(out["calibration"]).to_string(index=False))
    m = pd.DataFrame(out["metrics"])
    if not m.empty:
        print("\n" + m[m.scope == "endpoint"].to_string(index=False))
    print(f"\norigins executed: {out['n_origins_executed']} of {cfg.n_origins} requested; saved: {out['run_dir']}")
    if any(r["factor"] is None for r in out["calibration"]):
        print("factor = None: too few calibration origins for this level; the raw band stays in use.")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    conn = services.open_db()
    cfg = BacktestConfig(lookback=args.lookback, n_paths=args.n_paths, rebalance_every=args.rebalance_every,
                         n_decisions=args.n_decisions, initial_cash=args.cash,
                         costs=Costs(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps))
    params, source = services.signal_params(args.symbol, args.model, services.backtest_start(conn, args.symbol, cfg),
                                            horizon=args.horizon, min_edge=args.min_edge)
    res, summary = services.backtest(conn, args.symbol, args.model, params, cfg, source, args.device)
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


def cmd_paper(args: argparse.Namespace) -> int:
    conn = services.open_db()
    if args.action == "init":
        simulator.init_account(conn, args.cash)
        print(f"paper account created with {args.cash:,.2f} of SIMULATED money")
    elif args.action == "step":
        _show(services.paper_step(conn, args.symbol, args.model, args.n_paths, args.lookback, args.device))
    else:
        _show(services.paper_status(conn))
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

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--symbol", default=config.DEFAULT_SYMBOLS[0])
        sp.add_argument("--model", choices=MODEL_NAMES, default=BASELINE)
        sp.add_argument("--device", choices=["cpu", "auto"], default="cpu")
        sp.add_argument("--lookback", type=positive_int, default=400)
        sp.add_argument("--n-paths", type=path_count, default=20)

    sp = sub.add_parser("data")
    sp.add_argument("action", choices=["update", "demo", "import", "status"])
    sp.add_argument("--symbols", nargs="+", default=list(config.DEFAULT_SYMBOLS))
    sp.add_argument("--symbol")
    sp.add_argument("--csv")
    sp.add_argument("--rows", type=positive_int, default=900)
    sp.set_defaults(func=cmd_data)

    sub.add_parser("models").set_defaults(func=cmd_models)

    sp = sub.add_parser("forecast")
    common(sp)
    sp.add_argument("--horizon", type=positive_int, default=30)
    sp.set_defaults(func=cmd_forecast)

    sp = sub.add_parser("calibrate")
    common(sp)
    sp.add_argument("--horizons", type=positive_int, nargs="+", default=[7, 14, 30])
    sp.add_argument("--n-origins", type=positive_int, default=16)
    sp.add_argument("--stride", type=positive_int, default=None)
    sp.add_argument("--calib-fraction", type=float, default=0.5)
    sp.add_argument("--level", type=float, default=0.8)
    sp.set_defaults(func=cmd_calibrate)

    sp = sub.add_parser("backtest")
    common(sp)
    sp.add_argument("--horizon", type=positive_int, default=7)
    sp.add_argument("--min-edge", type=float, default=0.02)
    sp.add_argument("--rebalance-every", type=positive_int, default=7)
    sp.add_argument("--n-decisions", type=positive_int, default=26)
    sp.add_argument("--cash", type=float, default=10_000.0)
    sp.add_argument("--fee-bps", type=float, default=10.0)
    sp.add_argument("--slippage-bps", type=float, default=5.0)
    sp.set_defaults(func=cmd_backtest)

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
