"""Public domain model — Decimal for money, frozen for safety."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

Symbol = str
Resolution = Literal["daily", "minute"]


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class Board(StrEnum):
    RG = "RG"
    TN = "TN"
    NG = "NG"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    lots: int


@dataclass(frozen=True, slots=True)
class Candle:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    value: Decimal
    freq: int | None = None


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: Symbol
    price: Decimal
    volume: int
    side: Side
    board: Board
    ts: datetime
    seq: int
    change: Decimal | None = None
    change_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: Symbol
    last: Decimal
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    value: Decimal | None
    freq: int | None
    avg: Decimal | None
    ts: datetime
    is_index: bool = False


@dataclass(frozen=True, slots=True)
class Book:
    symbol: Symbol
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    ts: datetime
    seq: int


@dataclass(frozen=True, slots=True)
class KeyStats:
    symbol: Symbol
    raw: dict


@dataclass(frozen=True, slots=True)
class Mover:
    symbol: Symbol
    last: Decimal
    change: Decimal
    change_pct: Decimal
