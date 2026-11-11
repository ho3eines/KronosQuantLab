"""OHLCV validation and cleaning.

Cleaning is deliberately conservative: it sorts, drops exact-timestamp duplicates
and drops candles that had not closed yet. It never invents, interpolates or
edits prices. Anything else (nulls, impossible prices, time gaps) is *reported*
and makes the dataset not ``ok``; the caller decides, the data is not patched.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from app.core.errors import DataValidationError

REQUIRED = ("timestamp", "open", "high", "low", "close", "volume", "amount")
PRICE = ("open", "high", "low", "close")


def validate_ohlcv(
    df: pd.DataFrame, freq: str = "1D", now: dt.datetime | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return ``(clean_df, report)``. ``report['ok']`` is True only if nothing is wrong."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise DataValidationError(f"missing columns: {missing}")
    if df.empty:
        raise DataValidationError("empty dataset")
    step = pd.Timedelta(freq)
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    report: dict[str, Any] = {"rows_in": int(len(out)), "freq": freq}

    report["was_sorted"] = bool(out["timestamp"].is_monotonic_increasing)
    out = out.sort_values("timestamp", kind="stable")

    dup = out["timestamp"].duplicated(keep="first")
    report["duplicates_dropped"] = int(dup.sum())
    out = out[~dup]

    # A candle is complete only once its period has ended.
    if now is not None:
        now_ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
        incomplete = out["timestamp"] + step > now_ts
        report["incomplete_dropped"] = int(incomplete.sum())
        out = out[~incomplete]
    else:
        report["incomplete_dropped"] = None  # not checked
    out = out.reset_index(drop=True)
    if out.empty:
        raise DataValidationError("no complete candles left after cleaning")

    cols = list(REQUIRED[1:])
    null_rows = out[cols].isnull().any(axis=1)
    bad_price = (
        (out[list(PRICE)] <= 0).any(axis=1)
        | (out["high"] < out[["open", "close", "low"]].max(axis=1))
        | (out["low"] > out[["open", "close", "high"]].min(axis=1))
    ) & ~null_rows
    bad_volume = ((out["volume"] < 0) | (out["amount"] < 0)) & ~null_rows
    off_grid = (out["timestamp"] - out["timestamp"].dt.floor(freq)) != pd.Timedelta(0)
    deltas = out["timestamp"].diff().dropna()
    gap_idx = deltas.index[deltas != step]

    def stamps(mask: pd.Series) -> list[str]:
        return [t.isoformat() for t in out.loc[mask, "timestamp"].head(20)]

    report.update({
        "rows_out": int(len(out)),
        "first": out["timestamp"].iloc[0].isoformat(),
        "last": out["timestamp"].iloc[-1].isoformat(),
        "null_rows": int(null_rows.sum()),
        "null_examples": stamps(null_rows),
        "invalid_price_rows": int(bad_price.sum()),
        "invalid_price_examples": stamps(bad_price),
        "negative_volume_rows": int(bad_volume.sum()),
        "zero_volume_rows": int((out["volume"] == 0).sum()),  # warning only
        "off_grid_rows": int(off_grid.sum()),
        "gaps": int(len(gap_idx)),
        "gap_examples": [
            {"after": out["timestamp"].iloc[i - 1].isoformat(), "next": out["timestamp"].iloc[i].isoformat()}
            for i in list(gap_idx)[:20]
        ],
    })
    report["ok"] = not any(
        report[k] for k in ("null_rows", "invalid_price_rows", "negative_volume_rows", "off_grid_rows", "gaps")
    )
    return out, report


def require_ok(report: dict[str, Any]) -> None:
    if not report.get("ok"):
        problems = {k: v for k, v in report.items() if k.endswith(("_rows", "gaps")) and v}
        raise DataValidationError(f"dataset failed validation: {problems}")
