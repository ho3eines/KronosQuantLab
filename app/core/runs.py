"""Run directories and result files that are never silently overwritten."""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

from app.core.errors import OverwriteRefusedError


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def new_run_dir(base: Path, kind: str, now: dt.datetime | None = None) -> Path:
    """Create ``base/<kind>_<UTC stamp>``; if it exists, add a counter instead of reusing it."""
    stamp = (now or utc_now()).strftime("%Y%m%dT%H%M%SZ")
    base.mkdir(parents=True, exist_ok=True)
    for suffix in [""] + [f"_{i}" for i in range(1, 1000)]:
        path = base / f"{kind}_{stamp}{suffix}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise OverwriteRefusedError(f"could not allocate a fresh run directory under {base}")


def write_text_new(path: Path, text: str, force: bool = False) -> Path:
    """Write a file; refuse to replace an existing one unless ``force`` is given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w" if force else "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError as exc:
        raise OverwriteRefusedError(f"{path} already exists; pass force to overwrite") from exc
    return path


def to_jsonable(obj: Any) -> Any:
    """Plain-JSON form: numpy scalars/arrays become numbers/lists, NaN and inf become null."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "tolist") and not isinstance(obj, (str, bytes)):  # numpy scalar or array
        return to_jsonable(obj.tolist())
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    return str(obj)


def dumps(payload: Any) -> str:
    return json.dumps(to_jsonable(payload), indent=2, ensure_ascii=False, allow_nan=False)


def write_json_new(path: Path, payload: Any, force: bool = False) -> Path:
    return write_text_new(path, dumps(payload), force)


def safe_console() -> None:
    """Never let an un-encodable character (e.g. a non-ASCII path on a cp1252 Windows
    console) crash a command: such characters are printed as escapes instead."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def latest_run_dir(base: Path, kind: str) -> Path | None:
    runs = sorted(p for p in base.glob(f"{kind}_*") if p.is_dir())
    return runs[-1] if runs else None
