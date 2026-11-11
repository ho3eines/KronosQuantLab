"""Load/inference timing and resource measurement for one forecaster."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.core.errors import KQLError
from app.forecast.base import Forecaster

log = logging.getLogger(__name__)


class ResourceMonitor:
    """Samples this process's RSS and CPU use in a background thread (needs psutil)."""

    def __init__(self, interval: float = 0.2) -> None:
        import psutil

        self._proc = psutil.Process(os.getpid())
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_rss = self._proc.memory_info().rss
        self._cpu: list[float] = []

    def rss(self) -> int:
        return int(self._proc.memory_info().rss)

    def _loop(self) -> None:
        self._proc.cpu_percent(None)
        while not self._stop.wait(self._interval):
            self.peak_rss = max(self.peak_rss, self.rss())
            self._cpu.append(self._proc.cpu_percent(None))

    def __enter__(self) -> "ResourceMonitor":
        self.peak_rss = self.rss()
        self._cpu = []
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        self.peak_rss = max(self.peak_rss, self.rss())

    @property
    def mean_cpu_percent(self) -> float | None:
        """Percent of ONE logical CPU (400 = four logical CPUs fully busy)."""
        return float(np.mean(self._cpu)) if self._cpu else None


def _mb(n: int) -> float:
    return round(n / 1024**2, 1)


def _vram_peak_mb(device: str) -> float | None:
    if not device.startswith("cuda"):
        return None
    import torch

    return _mb(int(torch.cuda.max_memory_allocated()))


def benchmark_forecaster(
    factory: Callable[[], Forecaster],
    context: pd.DataFrame,
    future_ts: pd.Series,
    stages: tuple[int, ...] = (1, 5, 20),
    repeats: int = 3,
    budget_seconds: float = 600.0,
    seed: int = 1234,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """Benchmark one model; returns ``(result, raw paths of the largest completed stage)``.

    Stages escalate the number of sample paths. Escalation stops when a stage
    fails or one run exceeds ``budget_seconds``; what was actually executed is
    recorded separately from what was requested. Never raises for model errors.
    """
    mon = ResourceMonitor()
    result: dict[str, Any] = {
        "status": "ok", "requested_stages": list(stages), "repeats_requested": repeats,
        "horizon": int(len(future_ts)), "lookback": int(len(context)), "seed": seed,
        "rss_before_load_mb": _mb(mon.rss()), "stages": [], "logical_cpus": os.cpu_count(),
    }
    try:
        with mon:
            start = time.perf_counter()
            fc = factory()
            result["load_seconds"] = round(time.perf_counter() - start, 3)
    except (KQLError, MemoryError) as exc:
        result.update(status="load_failed", error=f"{type(exc).__name__}: {exc}")
        return result, None
    device = getattr(fc, "device", "n/a")
    result.update(
        model=fc.name, device=device, rss_after_load_mb=_mb(mon.rss()),
        peak_rss_load_mb=_mb(mon.peak_rss), n_parameters=getattr(fc, "n_parameters", None),
    )
    raw: np.ndarray | None = None
    try:
        start = time.perf_counter()
        fc.sample_paths(context, future_ts, 1, seed)  # warm-up, not timed below
        result["warmup_seconds"] = round(time.perf_counter() - start, 3)
        a = fc.sample_paths(context, future_ts, 2, seed)
        b = fc.sample_paths(context, future_ts, 2, seed)
        result["same_seed_reproducible"] = bool(np.array_equal(a, b))
        result["paths_differ_within_batch"] = bool(not np.array_equal(a[0], a[1]))
    except (KQLError, MemoryError) as exc:
        result.update(status="warmup_failed", error=f"{type(exc).__name__}: {exc}")
        return result, None

    for n_paths in stages:
        stage: dict[str, Any] = {"n_paths": n_paths, "runs_seconds": []}
        try:
            if device.startswith("cuda"):
                import torch

                torch.cuda.reset_peak_memory_stats()
            with mon:
                for r in range(repeats):
                    start = time.perf_counter()
                    out = fc.sample_paths(context, future_ts, n_paths, seed + r)
                    stage["runs_seconds"].append(round(time.perf_counter() - start, 3))
                    if r == 0:
                        first = out
                    if stage["runs_seconds"][-1] > budget_seconds:
                        stage["stopped_reason"] = f"a run exceeded the {budget_seconds:.0f}s budget"
                        break
            raw = first
        except (KQLError, MemoryError) as exc:
            stage["error"] = f"{type(exc).__name__}: {exc}"
            result["stages"].append(stage)
            result["status"] = "stage_failed"
            break
        runs = stage["runs_seconds"]
        stage.update(
            runs_executed=len(runs), mean_seconds=round(float(np.mean(runs)), 3),
            min_seconds=min(runs), max_seconds=max(runs),
            seconds_per_path_step=round(float(np.mean(runs)) / (n_paths * len(future_ts)), 4),
            peak_rss_mb=_mb(mon.peak_rss), mean_cpu_percent=mon.mean_cpu_percent,
            peak_vram_mb=_vram_peak_mb(device), output_shape=list(out.shape),
        )
        result["stages"].append(stage)
        log.info("%s n_paths=%d mean %.2fs peak RSS %.0f MB", fc.name, n_paths, stage["mean_seconds"], stage["peak_rss_mb"])
        if "stopped_reason" in stage:
            break
    done = [s["n_paths"] for s in result["stages"] if "error" not in s]
    result["max_paths_requested"] = max(stages)
    result["max_paths_executed"] = max(done) if done else 0
    return result, raw
