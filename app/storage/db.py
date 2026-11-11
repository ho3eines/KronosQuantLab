"""SQLite storage (stdlib sqlite3). One local file; no server, no cloud."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.runs import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume REAL NOT NULL, amount REAL NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS forecast_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL, symbol TEXT NOT NULL,
    model TEXT NOT NULL, origin_ts TEXT NOT NULL, last_close REAL NOT NULL, horizon INTEGER NOT NULL,
    n_paths INTEGER NOT NULL, seed INTEGER NOT NULL, lookback INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast_quantiles (
    run_id INTEGER NOT NULL REFERENCES forecast_runs(id), step INTEGER NOT NULL, ts TEXT NOT NULL,
    p10 REAL NOT NULL, p50 REAL NOT NULL, p90 REAL NOT NULL, PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL, initial_cash REAL NOT NULL, created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_positions (symbol TEXT PRIMARY KEY, qty REAL NOT NULL);
CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL, symbol TEXT NOT NULL,
    decision_ts TEXT NOT NULL, action TEXT NOT NULL, target_fraction REAL, status TEXT NOT NULL,
    fill_ts TEXT, fill_price REAL, qty_delta REAL, fee REAL, detail TEXT,
    UNIQUE (symbol, decision_ts)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_utc TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL
);
-- The audit log is append-only: updates and deletes are rejected by the database itself.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def audit(conn: sqlite3.Connection, event: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts_utc, event, payload) VALUES (?, ?, ?)",
        (utc_now().isoformat(timespec="seconds"), event, json.dumps(payload, default=str, ensure_ascii=False)),
    )
