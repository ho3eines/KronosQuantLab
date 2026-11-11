"""Simulated fills with fee and slippage. Pure arithmetic; there is no broker connection."""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.errors import require


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 10.0  # charged on traded notional
    slippage_bps: float = 5.0  # buys fill above, sells below the reference price
    min_trade_fraction: float = 0.005  # ignore rebalances smaller than this share of equity

    def __post_init__(self) -> None:
        for name in ("fee_bps", "slippage_bps", "min_trade_fraction"):
            value = getattr(self, name)
            require(math.isfinite(value) and value >= 0, f"{name} must be a non-negative number, got {value}")
        require(self.slippage_bps < 10_000, "slippage_bps must be below 10000")


@dataclass(frozen=True)
class Fill:
    cash: float
    qty: float
    qty_delta: float
    price: float
    fee: float


def rebalance(cash: float, qty: float, ref_price: float, target_fraction: float, costs: Costs) -> Fill:
    """Move the position towards ``target_fraction`` of equity at ``ref_price`` (e.g. next open).

    Long-only and unleveraged: the fraction is clamped to [0, 1] and a buy can never
    spend more cash than is available after paying the fee.
    """
    target_fraction = min(max(target_fraction, 0.0), 1.0)
    equity = cash + qty * ref_price
    if equity <= 0 or ref_price <= 0:
        return Fill(cash, qty, 0.0, ref_price, 0.0)
    delta_value = target_fraction * equity - qty * ref_price
    if abs(delta_value) < costs.min_trade_fraction * equity:
        return Fill(cash, qty, 0.0, ref_price, 0.0)
    fee_rate = costs.fee_bps / 1e4
    slip = costs.slippage_bps / 1e4
    if delta_value > 0:
        price = ref_price * (1 + slip)
        spend = min(delta_value, cash / (1 + fee_rate))
        dq = spend / price
        fee = spend * fee_rate
        return Fill(max(cash - spend - fee, 0.0), qty + dq, dq, price, fee)
    price = ref_price * (1 - slip)
    dq = min(-delta_value / ref_price, qty)
    proceeds = dq * price
    fee = proceeds * fee_rate
    return Fill(cash + proceeds - fee, max(qty - dq, 0.0), -dq, price, fee)
