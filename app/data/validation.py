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
    df: pd.DataFrame, freq: str = "1D", now: dt.datetime | None = None, *,
    utc_grid: bool = True, strict_gaps: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return ``(clean_df, report)``. ``report['ok']`` is True only if nothing fatal is wrong.

    ``utc_grid=False`` marks a venue whose bars are not aligned to UTC interval
    boundaries (Nobitex uses Iran time, MT5 exports use broker server time);
    ``strict_gaps=False`` marks a calendar whose holes are expected (FX weekends
    and holidays).  Both cases are still *reported* under ``warnings``, and the
    values themselves are never invented or patched.
    """
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise DataValidationError(f"missing columns: {missing}")
    if df.empty:
        raise DataValidationError("empty dataset")
    step = pd.Timedelta(freq)
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    report: dict[str, Any] = {"rows_in": int(len(out)), "freq": freq,
                              "utc_grid": bool(utc_grid), "strict_gaps": bool(strict_gaps)}

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
    fatal_keys = ["null_rows", "invalid_price_rows", "negative_volume_rows"]
    if utc_grid:
        fatal_keys.append("off_grid_rows")
    if strict_gaps:
        fatal_keys.append("gaps")
    report["fatal_problems"] = {k: report[k] for k in fatal_keys if report[k]}
    report["warnings"] = []
    if not utc_grid and report["off_grid_rows"]:
        report["warnings"].append(
            f"{report['off_grid_rows']} bars are not aligned to UTC {freq} boundaries "
            "(venue-native timestamps were kept as returned)"
        )
    if not strict_gaps and report["gaps"]:
        report["warnings"].append(
            f"{report['gaps']} gaps are expected outside the venue's trading sessions "
            "(weekends/holidays); the stored series is not patched"
        )
    if report["zero_volume_rows"] and report["zero_volume_rows"] == report["rows_out"]:
        report["warnings"].append("every bar reports zero volume")
    report["ok"] = not report["fatal_problems"]
    return out, report


def require_ok(report: dict[str, Any]) -> None:
    if not report.get("ok"):
        problems = report.get("fatal_problems") or {
            k: v for k, v in report.items() if k.endswith(("_rows", "gaps")) and v
        }
        raise DataValidationError(f"dataset failed validation: {problems}")
