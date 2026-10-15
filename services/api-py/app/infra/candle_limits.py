"""Finite candle budgets shared by the HTTP surface and provider."""

from typing import Final

MAX_DAILY_DAYS: Final = 3660
MAX_MINUTE_DAYS: Final = 31
MAX_CANDLES: Final = 20_000
MAX_SCANNED_CANDLES: Final = 50_000
MAX_CANDLE_BYTES: Final = 5_000_000
MAX_CANDLE_LINE_BYTES: Final = 65_536
CANDLE_TIMEOUT_SECONDS: Final = 30.0


class CandleBudgetExceeded(ValueError):
    def __init__(self, resource: str, limit: int) -> None:
        self.resource = resource
        self.limit = limit
        super().__init__(f"Candle {resource} budget exceeded ({limit})")


class CandleDataError(RuntimeError):
    """The source did not provide a complete valid candle envelope."""
