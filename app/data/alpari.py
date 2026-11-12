"""Alpari data via MetaTrader 5 history export - no login, no account, no orders.

Alpari is a MetaTrader broker: it has **no public, credential-free REST
market-data API**, and the MetaTrader terminal itself needs an account login.
This project is research-only and never handles credentials or sends orders, so
the supported route is a file the user exports themselves:

    MetaTrader 5 -> Toolbox -> History -> right click -> Export -> CSV

``read_mt5_csv`` understands that export: tab / semicolon / comma delimiters,
``<DATE>``/``<TIME>`` or ``Date``/``Time`` headers, day-first dates, and MT5's
tick volume.  The venue reports no quote volume, so ``amount`` is derived as
``volume * close`` and the report says so.

MT5 timestamps are broker server time, not UTC.  They are converted with an
explicit ``tz_offset_hours`` (default 0 = "treat the export as UTC") and the
choice is recorded in the import report; nothing is guessed silently.
"""
from __future__ import annotations

import codecs
import io
import re
from pathlib import Path
from typing import Any, TextIO

import pandas as pd

from app.core import timeframes
from app.core.errors import ConfigError, DataValidationError

REQUIRED = ("timestamp", "open", "high", "low", "close", "volume", "amount")
POSITIONAL = ["date", "time", "open", "high", "low", "close", "tickvol", "volume", "spread"]
DELIMITERS = {"\t": "tab", ";": "semicolon", ",": "comma"}
DATE_HINTS = ("date", "datetime", "timestamp", "time")


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Decode an MT5 export's bytes; returns ``(text, encoding actually used)``.

    MetaTrader writes its "Unicode" export as UTF-16 (usually with a BOM, sometimes
    without) and the ANSI export as UTF-8/Windows-1252.  A UTF-16 file decoded as
    cp1252 "succeeds" but yields NUL-riddled text that later looks like a broken
    DATE column, so the BOM/NUL check has to come first.
    """
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace"), "utf-16"
    if b"\x00" in raw:  # UTF-16 without a BOM: every ASCII char has a NUL partner
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            return text, encoding
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacement characters)"


def load_text(source: str | Path | TextIO) -> tuple[str, str | None]:
    """``(text, encoding)``; ``encoding`` is ``None`` when the caller passed text."""
    if hasattr(source, "read"):
        text = source.read()  # type: ignore[union-attr]
        return (text, None) if isinstance(text, str) else decode_bytes(text)
    if not isinstance(source, Path):
        return str(source), None  # the caller already has the text
    path = source
    if not path.is_file():
        raise DataValidationError(f"CSV not found: {path}")
    return decode_bytes(path.read_bytes())


def read_text(source: str | Path | TextIO) -> str:
    """CSV text from a file path, a file object, or the text itself (``str``)."""
    return load_text(source)[0]


def looks_like_mt5(source: str | Path | TextIO) -> bool:
    """True when the file looks like an MT5 history export (used by ``--format auto``)."""
    try:
        text = read_text(source)
    except DataValidationError:
        return False
    lines = [line for line in text.splitlines()[:3] if line.strip()]
    if not lines:
        return False
    first = lines[0].lower().replace(" ", "")
    return ("<date>" in first or "tickvol" in first or "date,time" in first
            or ("\t" in lines[0] and "open" in first and "close" in first))


def _delimiter(text: str) -> str:
    lines = [line for line in text.splitlines()[:5] if line.strip()]
    if not lines:
        raise DataValidationError("the CSV is empty")
    counts = {d: sum(line.count(d) for line in lines) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    if counts[best] == 0:
        raise ConfigError("could not detect a delimiter (expected tab, ';' or ','); export the MT5 history as CSV")
    return best


def _header_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).strip().strip("<>[]").lower())


def _frame(text: str, delimiter: str) -> tuple[pd.DataFrame, bool]:
    raw = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, header=None, skip_blank_lines=True)
    if raw.empty:
        raise DataValidationError("the CSV has no rows")
    first = [_header_key(v) for v in raw.iloc[0].tolist()]
    looks_like_header = any(k in {"date", "datetime", "timestamp", "time"} for k in first) or any(
        k in {"open", "high", "low", "close"} for k in first
    )
    if looks_like_header:
        raw = raw.iloc[1:].reset_index(drop=True)
        raw.columns = first  # type: ignore[assignment]
    else:
        width = raw.shape[1]
        raw.columns = POSITIONAL[:width] + [f"column{i}" for i in range(width - len(POSITIONAL))]  # type: ignore[assignment]
    return raw, looks_like_header


def _pick(columns: list[str], *names: str) -> str | None:
    for name in names:
        if name in columns:
            return name
    return None


def _numbers(values: pd.Series, delimiter: str) -> pd.Series:
    text = values.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False).str.strip()
    if delimiter != ",":  # a semicolon/tab export may use a decimal comma
        text = text.str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


def read_mt5_csv(
    source: str | Path | TextIO, interval: str | None = None, *, tz_offset_hours: float = 0.0
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse an MT5 history export into the project's OHLCV frame + a report."""
    interval = timeframes.normalize(interval or "1d")
    text, encoding = load_text(source)
    delimiter = _delimiter(text)
    raw, had_header = _frame(text, delimiter)
    columns = [str(c) for c in raw.columns]

    date_col = _pick(columns, "date", "datetime", "timestamp")
    if date_col is None:
        raise ConfigError("could not find a DATE column in the MT5 export")
    time_col = _pick(columns, "time")
    open_col, high_col = _pick(columns, "open"), _pick(columns, "high")
    low_col, close_col = _pick(columns, "low"), _pick(columns, "close")
    if None in (open_col, high_col, low_col, close_col):
        raise ConfigError("could not find OPEN/HIGH/LOW/CLOSE columns in the MT5 export")
    volume_col = _pick(columns, "tickvol", "tickvolume", "volume", "vol")
    amount_col = _pick(columns, "amount", "turnover")

    dates = raw[date_col].astype(str).str.strip().str.replace(".", "-", regex=False)
    stamps = dates if time_col is None else dates + " " + raw[time_col].astype(str).str.strip()
    sample = next((v for v in dates if v and v.lower() not in ("nan", "none")), "")
    dayfirst = not bool(re.match(r"^\d{4}[-/]", sample))  # MT5 writes YYYY.MM.DD; others may be day-first
    parsed = pd.to_datetime(stamps, errors="coerce", dayfirst=dayfirst)
    bad_stamps = int(parsed.isna().sum())

    out = pd.DataFrame({
        "timestamp": parsed,
        "open": _numbers(raw[open_col], delimiter),
        "high": _numbers(raw[high_col], delimiter),
        "low": _numbers(raw[low_col], delimiter),
        "close": _numbers(raw[close_col], delimiter),
        "volume": _numbers(raw[volume_col], delimiter) if volume_col else 0.0,
        "amount": _numbers(raw[amount_col], delimiter) if amount_col else 0.0,
    })
    amount_derived = amount_col is None
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp", kind="stable")
    duplicates = int(out["timestamp"].duplicated(keep="last").sum())
    out = out.drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if amount_derived:  # the venue gives no quote volume
        out["amount"] = out["close"] * out["volume"]
    if tz_offset_hours:
        out["timestamp"] = out["timestamp"] - pd.Timedelta(hours=float(tz_offset_hours))
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    if out.empty:
        detail = "text" if encoding is None else encoding
        raise DataValidationError(
            "the MT5 export has no usable rows: no DATE could be parsed "
            f"(check the DATE format; the file was decoded as {detail})"
        )

    step = timeframes.step(interval)
    deltas = out["timestamp"].diff().dropna()
    median = deltas.median() if not deltas.empty else pd.Timedelta(0)
    if not deltas.empty:
        tolerance = max(pd.Timedelta(hours=2), step * 0.1)  # DST/server-clock drift on daily bars
        if abs(median - step) > tolerance:
            raise ConfigError(
                f"CSV bars are about {median} apart, not {step} ({interval}); export the matching timeframe"
            )

    report = {
        "format": "mt5",
        "encoding": encoding or "text passed in memory",
        "delimiter": DELIMITERS[delimiter],
        "header_detected": had_header,
        "rows": int(len(out)),
        "duplicate_timestamps": duplicates,
        "rows_without_timestamp": bad_stamps,
        "volume_column": volume_col or "none (set to 0)",
        "amount_derived": amount_derived,
        "amount_rule": "volume * close" if amount_derived else "reported by the export",
        "timezone": f"export minus {float(tz_offset_hours):g}h, then treated as UTC",
        "median_spacing": str(median),
        "calendar": "fx (weekend/holiday gaps are expected)",
    }
    return out[list(REQUIRED)], report
