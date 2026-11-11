"""P5: local paper-trading simulator.

This module CANNOT trade. It has no network code, no exchange client and takes no
credentials: "orders" are rows in the local SQLite file, filled by arithmetic at
the next stored candle's open. Every state change is written to an append-only
audit log.

Daily cycle (``step``), safe to run any number of times per day:
  1. fill pending orders for which a later candle now exists (at that candle's open);
  2. if no decision exists yet for the newest stored candle, make one and record it.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

import pandas as pd

from app.backtest.execution import Costs, rebalance
from app.core.errors import KQLError
from app.core.runs import utc_now
from app.forecast.base import Forecaster
from app.signals.pipeline import decide_at
from app.signals.rules import ABSTAIN, SignalParams
from app.storage.db import audit

log = logging.getLogger(__name__)


class PaperError(KQLError):
    pass


def init_account(conn: sqlite3.Connection, initial_cash: float = 10_000.0) -> None:
    if initial_cash <= 0:
        raise PaperError("initial cash must be positive")
    if conn.execute("SELECT 1 FROM paper_account").fetchone():
        raise PaperError("paper account already exists; it is never reset implicitly")
    with conn:
        conn.execute("INSERT INTO paper_account VALUES (1, ?, ?, ?)",
                     (initial_cash, initial_cash, utc_now().isoformat(timespec="seconds")))
        audit(conn, "paper_init", {"initial_cash": initial_cash, "note": "simulated money"})


def _account(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM paper_account").fetchone()
    if row is None:
        raise PaperError("no paper account. Run: python scripts/kql.py paper init")
    return row


def _qty(conn: sqlite3.Connection, symbol: str) -> float:
    row = conn.execute("SELECT qty FROM paper_positions WHERE symbol = ?", (symbol,)).fetchone()
    return float(row["qty"]) if row else 0.0


def fill_pending(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, costs: Costs) -> list[dict[str, Any]]:
    fills = []
    pending = conn.execute(
        "SELECT * FROM paper_orders WHERE symbol = ? AND status = 'PENDING' ORDER BY decision_ts", (symbol,)
    ).fetchall()
    for order in pending:
        later = df[df["timestamp"] > pd.Timestamp(order["decision_ts"])]
        if later.empty:
            continue  # the next candle does not exist yet
        bar = later.iloc[0]
        cash, qty = float(_account(conn)["cash"]), _qty(conn, symbol)
        fill = rebalance(cash, qty, float(bar["open"]), float(order["target_fraction"]), costs)
        status = "FILLED" if fill.qty_delta != 0.0 else "NO_CHANGE"
        info = {"order_id": order["id"], "symbol": symbol, "status": status, "fill_ts": str(bar["timestamp"]),
                "price": fill.price, "qty_delta": fill.qty_delta, "fee": fill.fee, "cash_after": fill.cash,
                "qty_after": fill.qty}
        with conn:
            conn.execute("UPDATE paper_account SET cash = ? WHERE id = 1", (fill.cash,))
            conn.execute("INSERT INTO paper_positions VALUES (?, ?) ON CONFLICT(symbol) DO UPDATE SET qty = excluded.qty",
                         (symbol, fill.qty))
            conn.execute("UPDATE paper_orders SET status = ?, fill_ts = ?, fill_price = ?, qty_delta = ?, fee = ? WHERE id = ?",
                         (status, str(bar["timestamp"]), fill.price, fill.qty_delta, fill.fee, order["id"]))
            audit(conn, "paper_fill", info)
        fills.append(info)
    return fills


def step(
    conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, forecaster: Forecaster, params: SignalParams,
    lookback: int = 400, n_paths: int = 20, costs: Costs = Costs(), base_seed: int = 20260101,
) -> dict[str, Any]:
    _account(conn)
    df = df.reset_index(drop=True)
    result: dict[str, Any] = {"symbol": symbol, "fills": fill_pending(conn, symbol, df, costs), "decision": None}
    last_ts = str(df["timestamp"].iloc[-1])
    if conn.execute("SELECT 1 FROM paper_orders WHERE symbol = ? AND decision_ts = ?", (symbol, last_ts)).fetchone():
        result["note"] = f"decision for {last_ts[:10]} already recorded"
        return result
    try:
        ctx = decide_at(df, len(df) - 1, forecaster, params, lookback, n_paths, base_seed)
    except KQLError as exc:
        with conn:
            audit(conn, "paper_decision_failed", {"symbol": symbol, "decision_ts": last_ts, "error": str(exc)})
        result["error"] = str(exc)
        return result
    d = ctx.decision
    status = "ABSTAIN" if d.action == ABSTAIN else "PENDING"
    detail = {"model": forecaster.name, **d.as_dict(), "regime": ctx.regime.as_dict(), "last_close": ctx.forecast.last_close}
    with conn:
        conn.execute(
            "INSERT INTO paper_orders (created_utc, symbol, decision_ts, action, target_fraction, status, detail) "
            "VALUES (?,?,?,?,?,?,?)",
            (utc_now().isoformat(timespec="seconds"), symbol, last_ts, d.action, d.target_fraction, status,
             "; ".join(d.reasons)),
        )
        audit(conn, "paper_decision", {"symbol": symbol, "decision_ts": last_ts, "status": status, **detail})
    result["decision"] = {"decision_ts": last_ts, "action": d.action, "target_fraction": d.target_fraction,
                          "status": status, "reasons": d.reasons}
    return result


def account_status(conn: sqlite3.Connection, last_prices: dict[str, float]) -> dict[str, Any]:
    acct = _account(conn)
    positions = []
    value = 0.0
    for row in conn.execute("SELECT symbol, qty FROM paper_positions WHERE qty > 0 ORDER BY symbol"):
        price = last_prices.get(row["symbol"])
        worth = row["qty"] * price if price is not None else None
        value += worth or 0.0
        positions.append({"symbol": row["symbol"], "qty": row["qty"], "last_price": price, "value": worth})
    equity = float(acct["cash"]) + value
    return {"cash": float(acct["cash"]), "initial_cash": float(acct["initial_cash"]), "equity": equity,
            "return": equity / float(acct["initial_cash"]) - 1.0, "positions": positions, "simulated": True}


def orders_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM paper_orders ORDER BY id DESC", conn)


def audit_frame(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", conn, params=(limit,))
