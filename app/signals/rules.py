"""P3: BUY / SELL / ABSTAIN research rules and position sizing.

RESEARCH ONLY.  The default thresholds are placeholders chosen for readability,
not values validated on data; nothing here is a recommendation and no decision
is ever sent anywhere except the local backtester / paper simulator.

Long-only spot semantics: BUY = hold a long position of ``target_fraction`` of
equity; SELL = be flat (there is no shorting); ABSTAIN = leave the position as is.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.signals.regime import Regime

BUY, SELL, ABSTAIN = "BUY", "SELL", "ABSTAIN"


@dataclass(frozen=True)
class SignalParams:
    horizon: int = 7  # forecast step the rule looks at
    min_edge: float = 0.02  # |median forecast return| needed to act
    max_downside: float = 0.10  # BUY only if the P10 return is above -max_downside
    abstain_in_high_vol: bool = True
    block_buy_in_downtrend: bool = True
    target_annual_vol: float = 0.40  # volatility-targeted sizing
    max_fraction: float = 1.0  # never leveraged
    interval_factor: float = 1.0  # calibration factor applied to the P10-P90 band


@dataclass(frozen=True)
class Decision:
    action: str
    target_fraction: float | None  # None for ABSTAIN (keep current position)
    r10: float
    r50: float
    r90: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def position_fraction(realized_vol_annual: float, params: SignalParams) -> float:
    """Volatility targeting, capped at ``max_fraction`` (<= 1, i.e. no leverage)."""
    cap = min(max(params.max_fraction, 0.0), 1.0)
    if realized_vol_annual <= 0:
        return 0.0
    return float(min(cap, params.target_annual_vol / realized_vol_annual))


def decide(p10: float, p50: float, p90: float, last_close: float, regime: Regime, params: SignalParams) -> Decision:
    """Quantiles are RAW close forecasts at ``params.horizon``; the calibration factor is applied here."""
    lo = p50 - params.interval_factor * (p50 - p10)
    hi = p50 + params.interval_factor * (p90 - p50)
    r10, r50, r90 = lo / last_close - 1.0, p50 / last_close - 1.0, hi / last_close - 1.0
    why: list[str] = [f"regime={regime.trend}/{regime.volatility}", f"r10={r10:+.3f} r50={r50:+.3f} r90={r90:+.3f}"]

    def done(action: str, fraction: float | None, reason: str) -> Decision:
        return Decision(action, fraction, r10, r50, r90, why + [reason])

    if r50 <= -params.min_edge:
        return done(SELL, 0.0, f"median return <= -{params.min_edge}")
    if params.abstain_in_high_vol and regime.volatility == "high":
        return done(ABSTAIN, None, "high-volatility regime")
    if r50 >= params.min_edge:
        if r10 < -params.max_downside:
            return done(ABSTAIN, None, f"P10 return below -{params.max_downside}")
        if params.block_buy_in_downtrend and regime.trend == "down":
            return done(ABSTAIN, None, "downtrend regime")
        return done(BUY, position_fraction(regime.realized_vol_annual, params), f"median return >= {params.min_edge}")
    return done(ABSTAIN, None, "median return inside the no-trade band")
