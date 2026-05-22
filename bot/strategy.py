"""
200-day SMA regime strategy: determines whether to hold TQQQ or BIL.
"""
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Regime(Enum):
    RISK_ON  = "RISK_ON"   # price >= SMA200 → hold TQQQ
    RISK_OFF = "RISK_OFF"  # price <  SMA200 → hold BIL


@dataclass
class StrategyResult:
    regime: Regime
    current_price: float
    sma_200: float


def evaluate(candles: list[dict], sma_period: int = 200) -> StrategyResult:
    """
    Given a list of daily candles (oldest-first), determine the current regime.

    RISK_ON  when today's close >= SMA(sma_period)
    RISK_OFF when today's close <  SMA(sma_period)
    """
    if len(candles) < sma_period:
        raise ValueError(
            f"Need at least {sma_period} candles to compute SMA; got {len(candles)}"
        )

    closes = [c["close"] for c in candles]
    sma = sum(closes[-sma_period:]) / sma_period
    price = closes[-1]
    regime = Regime.RISK_ON if price >= sma else Regime.RISK_OFF

    logger.info(
        "price=%.2f  SMA(%d)=%.2f  regime=%s",
        price, sma_period, sma, regime.value,
    )

    return StrategyResult(regime=regime, current_price=price, sma_200=sma)
