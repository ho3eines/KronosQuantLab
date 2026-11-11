"""Kronos Quant Lab - P0 command line (research only; no trading of any kind).

  python scripts/p0.py data                      fetch + validate BTCUSDT 1d (public endpoint)
  python scripts/p0.py models                    show license / size / disk (downloads nothing)
  python scripts/p0.py models --download --yes   download the checkpoints
  python scripts/p0.py benchmark --smoke         1 path, horizon 7, both models
  python scripts/p0.py benchmark                 staged 1 -> 5 -> 20 paths
  python scripts/p0.py evaluate                  rolling-origin accuracy vs naive baseline
  python scripts/p0.py report                    write docs/P0_model_benchmark.md
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import logging
import platform
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.core import config  # noqa: E402
from app.core.errors import KQLError  # noqa: E402
from app.core.runs import latest_run_dir, new_run_dir, utc_now, write_json_new, write_text_new  # noqa: E402

log = logging.getLogger("p0")


# ----------------------------------------------------------------------------- helpers
def _latest_clean(symbol: str) -> Path:
    files = sorted((config.DATASETS_DIR / "clean").glob(f"{symbol}_1d_*.csv"))
    if not files:
        raise KQLError("no local dataset found. Run: python scripts/p0.py data")
    return files[-1]


def _load_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    from app.data.validation import require_ok, validate_ohlcv

    path = Path(args.data) if args.data else _latest_clean(args.symbol)
    df = pd.read_csv(path)
    df, report = validate_ohlcv(df)  # re-validate what is actually on disk
    require_ok(report)
    info = {
        "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(df), "first": report["first"], "last": report["last"],
    }
    return df, info


def _factory(key: str, device: str, batch_size: int | None):
    from app.forecast.kronos_adapter import KronosForecaster

    spec = config.MODELS[key]
    return lambda: KronosForecaster.load(
        f"kronos-{key}", spec.local_dir, config.TOKENIZER.local_dir, device=device, batch_size=batch_size
    )


def _env_summary() -> dict[str, Any]:
    env: dict[str, Any] = {
        "Python": platform.python_version(), "OS": platform.platform(), "machine": platform.machine(),
        "numpy": np.__version__, "pandas": pd.__version__, "Kronos commit (pinned)": config.KRONOS_COMMIT,
    }
    try:
        import torch

        env["torch"] = torch.__version__
        env["torch threads"] = torch.get_num_threads()
        env["torch CUDA build"] = torch.version.cuda
    except Exception as exc:  # noqa: BLE001
        env["torch"] = f"unavailable ({type(exc).__name__})"
    try:
        import psutil

        env["RAM total GB"] = round(psutil.virtual_memory().total / 1024**3, 2)
        env["CPU physical / logical"] = f"{psutil.cpu_count(logical=False)} / {psutil.cpu_count()}"
    except Exception:  # noqa: BLE001
        pass
    return env


# ----------------------------------------------------------------------------- commands
def cmd_data(args: argparse.Namespace) -> int:
    from app.data.binance import fetch_klines, klines_to_frame
    from app.data.validation import validate_ohlcv

    now = utc_now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    rows = fetch_klines(args.symbol, "1d", config.BINANCE_BASE_URL)
    raw_path = config.DATASETS_DIR / "raw" / f"{args.symbol}_1d_{stamp}.json"
    write_json_new(raw_path, {
        "source": f"{config.BINANCE_BASE_URL}/api/v3/klines", "symbol": args.symbol, "interval": "1d",
        "fetched_at_utc": now.isoformat(), "rows": rows,
    })
    clean, report = validate_ohlcv(klines_to_frame(rows), now=now)
    clean_path = config.DATASETS_DIR / "clean" / f"{args.symbol}_1d_{stamp}.csv"
    write_text_new(clean_path, clean.to_csv(index=False))
    write_json_new(clean_path.with_suffix(".validation.json"), report)
    print(json.dumps(report, indent=2))
    print(f"\nraw:   {raw_path}\nclean: {clean_path}")
    if not report["ok"]:
        print("\nVALIDATION FAILED - data was saved but benchmark/evaluate will refuse to use it.")
        return 2
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from app.forecast import weights

    metas = {s.key: weights.inspect_repo(s) for s in weights.all_specs()}
    total = sum(m["total_bytes"] for m in metas.values())
    free = weights.free_bytes(config.MODELS_DIR)
    for key, m in metas.items():
        print(f"\n[{key}] {m['repo_id']}\n  commit : {m['resolved_sha']}\n  license: {m['license']}\n"
              f"  size   : {m['total_bytes'] / 1e6:.1f} MB")
        for f in m["files"]:
            print(f"    {f['name']}  {(f['bytes'] or 0) / 1e6:.2f} MB")
    print(f"\nTotal download: {total / 1e9:.3f} GB   Free disk: {free / 1e9:.2f} GB")
    unknown = [k for k, m in metas.items() if not m["license"]]
    if unknown:
        print(f"WARNING: no license declared in the model card of: {unknown}. Read the model pages before use.")
    if not args.download:
        print("\nNothing downloaded. To download: python scripts/p0.py models --download --yes")
        return 0
    if not args.yes:
        print("\nRefusing to download without --yes.")
        return 2
    if unknown and not args.accept_unknown_license:
        print("Refusing to download: license unknown. Re-run with --accept-unknown-license after reading it.")
        return 2
    weights.check_space(total, free)
    for spec in weights.all_specs():
        path = weights.download(spec, metas[spec.key])
        print(f"downloaded {spec.repo_id} -> {path}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from app.evaluation.benchmark import benchmark_forecaster
    from app.forecast.base import make_window
    from app.forecast.kronos_adapter import resolve_device, weights_bytes

    if args.smoke:
        args.stages, args.repeats, args.horizon = [1], 1, 7
    df, info = _load_dataset(args)
    win = make_window(df, len(df), args.lookback, args.horizon)  # latest window, identical for both
    device, reason = resolve_device(args.device)
    run_dir = new_run_dir(config.REPORTS_DIR, "smoke" if args.smoke else "benchmark")
    out: dict[str, Any] = {
        "kind": "benchmark", "created_utc": utc_now().isoformat(), "env": _env_summary(), "dataset": info,
        "device_reason": reason,
        "config": {"device_requested": args.device, "lookback": args.lookback, "horizon": args.horizon,
                   "stages": args.stages, "repeats": args.repeats, "budget_seconds": args.budget,
                   "batch_size": args.batch_size, "sampling": dataclasses.asdict(config.SamplingConfig())},
        "models": {},
    }
    for key in args.models:
        log.info("benchmarking %s on %s", key, device)
        result, raw = benchmark_forecaster(
            _factory(key, device, args.batch_size), win.context, win.future_ts,
            stages=tuple(args.stages), repeats=args.repeats, budget_seconds=args.budget,
        )
        local = config.MODELS[key].local_dir
        result["weights_mb"] = round(weights_bytes(local) / 1e6, 1) if local.is_dir() else None
        if raw is not None:
            np.save(run_dir / f"raw_{key}.npy", raw)
            result["raw_output"] = {"file": f"raw_{key}.npy", "shape": list(raw.shape),
                                    "axes": ["path", "step", "feature"], "features": list(config.FEATURE_COLUMNS),
                                    "first_step_timestamp": str(win.future_ts.iloc[0])}
        out["models"][key] = result
        print(json.dumps(result, indent=2, default=str))
    write_json_new(run_dir / "benchmark.json", out)
    print(f"\nSaved: {run_dir}")
    return 0 if all(r["status"] == "ok" for r in out["models"].values()) else 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    from app.evaluation.rolling import EvalConfig, endpoint_abs_errors, run_forecasts, summarize
    from app.forecast.kronos_adapter import resolve_device

    df, info = _load_dataset(args)
    cfg = EvalConfig(lookback=args.lookback, horizons=tuple(args.horizons), n_origins=args.n_origins,
                     stride=args.stride or max(args.horizons), n_paths=args.n_paths, seed=args.seed)
    device, reason = resolve_device(args.device)
    run_dir = new_run_dir(config.REPORTS_DIR, "evaluation")
    out: dict[str, Any] = {
        "kind": "evaluation", "created_utc": utc_now().isoformat(), "env": _env_summary(), "dataset": info,
        "device": device, "device_reason": reason, "config": dataclasses.asdict(cfg),
        "sampling": dataclasses.asdict(config.SamplingConfig()), "models": {}, "paired": [],
    }
    rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    for key in args.models:
        start = time.perf_counter()
        try:
            fc = _factory(key, device, args.batch_size)()
            res = run_forecasts(df, fc, cfg)
        except (KQLError, MemoryError) as exc:
            log.error("%s failed: %s", key, exc)
            out["models"][key] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            continue
        results[key] = res
        np.savez_compressed(run_dir / f"paths_{key}.npz", paths=res["paths"], actual=res["actual"],
                            last_close=res["last_close"], origins=np.asarray(res["origins"]))
        rows += summarize(res["paths"], res["actual"], res["last_close"], cfg.horizons, key)
        out["models"][key] = {
            "status": "ok" if not res["errors"] else "partial", "origins": res["origins"],
            "first_target_timestamp": res["first_target_timestamp"], "n_origins_executed": len(res["origins"]),
            "n_paths_requested": res["n_paths_requested"], "n_paths_executed": res["n_paths_executed"],
            "seconds_per_origin": res["seconds"], "total_seconds": round(time.perf_counter() - start, 1),
            "errors": res["errors"],
        }
    if {"small", "base"} <= results.keys():
        s, b = results["small"], results["base"]
        common = sorted(set(s["origins"]) & set(b["origins"]))
        if common:
            si = [s["origins"].index(o) for o in common]
            bi = [b["origins"].index(o) for o in common]
            for h in cfg.horizons:
                es = endpoint_abs_errors(s["paths"][si], s["actual"][si], h)
                eb = endpoint_abs_errors(b["paths"][bi], b["actual"][bi], h)
                en = np.abs(s["actual"][si][:, h - 1, config.CLOSE_INDEX] - s["last_close"][si])
                out["paired"].append({
                    "horizon": h, "n_common_origins": len(common),
                    "base_better_than_small": int((eb < es).sum()),
                    "small_better_than_naive": int((es < en).sum()),
                    "base_better_than_naive": int((eb < en).sum()),
                    "mean_abs_err_small": float(es.mean()), "mean_abs_err_base": float(eb.mean()),
                    "mean_abs_err_naive": float(en.mean()),
                })
    if rows:
        with (run_dir / "metrics.csv").open("x", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write_json_new(run_dir / "evaluation.json", out)
    print(pd.DataFrame(rows).to_string(index=False) if rows else "no metrics produced")
    print(f"\nSaved: {run_dir}")
    return 0 if rows and all(m["status"] == "ok" for m in out["models"].values()) else 1


def cmd_report(args: argparse.Namespace) -> int:
    from app.evaluation.report import render
    from app.forecast import weights

    bench_dir = latest_run_dir(config.REPORTS_DIR, "benchmark")
    eval_dir = latest_run_dir(config.REPORTS_DIR, "evaluation")
    bench = json.loads((bench_dir / "benchmark.json").read_text(encoding="utf-8")) if bench_dir else None
    evaluation = json.loads((eval_dir / "evaluation.json").read_text(encoding="utf-8")) if eval_dir else None
    rows: list[dict[str, Any]] = []
    if eval_dir and (eval_dir / "metrics.csv").is_file():
        rows = pd.read_csv(eval_dir / "metrics.csv").astype(object).where(lambda d: d.notna(), None).to_dict("records")
    env = (bench or evaluation or {}).get("env") or _env_summary()
    if bench_dir:
        env["benchmark run"] = bench_dir.name
    if eval_dir:
        env["evaluation run"] = eval_dir.name
    manifests = {s.key: weights.read_manifest(s) for s in weights.all_specs()}
    text = render(env, manifests, bench, evaluation, rows)
    target = config.REPO_ROOT / "docs" / "P0_model_benchmark.md"
    write_text_new(target, text, force=args.force)
    print(f"Wrote {target}")
    return 0


# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--symbol", default="BTCUSDT")
        sp.add_argument("--data", help="clean CSV to use (default: newest local one)")
        sp.add_argument("--models", nargs="+", choices=list(config.MODELS), default=list(config.MODELS))
        sp.add_argument("--device", choices=["cpu", "auto"], default="cpu",
                        help="'auto' uses CUDA only if a real self-test passes")
        sp.add_argument("--lookback", type=int, default=400)
        sp.add_argument("--batch-size", type=int, default=None, help="split sample paths into smaller batches")

    sp = sub.add_parser("data", help="fetch and validate public daily klines")
    sp.add_argument("--symbol", default="BTCUSDT")
    sp.set_defaults(func=cmd_data)

    sp = sub.add_parser("models", help="inspect (and optionally download) checkpoints")
    sp.add_argument("--download", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--accept-unknown-license", action="store_true")
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser("benchmark", help="load/inference time and memory")
    common(sp)
    sp.add_argument("--smoke", action="store_true", help="1 path, horizon 7, 1 timed run")
    sp.add_argument("--horizon", type=int, default=30)
    sp.add_argument("--stages", type=int, nargs="+", default=[1, 5, 20])
    sp.add_argument("--repeats", type=int, default=3)
    sp.add_argument("--budget", type=float, default=600.0, help="stop escalating if one run exceeds this many seconds")
    sp.set_defaults(func=cmd_benchmark)

    sp = sub.add_parser("evaluate", help="rolling-origin accuracy vs naive baseline")
    common(sp)
    sp.add_argument("--horizons", type=int, nargs="+", default=[7, 14, 30])
    sp.add_argument("--n-origins", type=int, default=8)
    sp.add_argument("--stride", type=int, default=None, help="bars between origins (default: max horizon)")
    sp.add_argument("--n-paths", type=int, default=20)
    sp.add_argument("--seed", type=int, default=20260101)
    sp.set_defaults(func=cmd_evaluate)

    sp = sub.add_parser("report", help="write docs/P0_model_benchmark.md from the newest results")
    sp.add_argument("--force", action="store_true", help="overwrite an existing report")
    sp.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return int(args.func(args))
    except KQLError as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
