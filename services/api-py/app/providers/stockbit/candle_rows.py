"""Parse complete source OHLC rows without fabricating missing observations."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)

from app.domain.models import Candle
from app.infra.candle_limits import CandleDataError


class SourceCandle(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    ts: datetime = Field(
        validation_alias=AliasChoices("timestamp", "time", "date", "datetime", "t")
    )
    open: Decimal = Field(validation_alias=AliasChoices("open", "o"))
    high: Decimal = Field(validation_alias=AliasChoices("high", "h"))
    low: Decimal = Field(validation_alias=AliasChoices("low", "l"))
    close: Decimal = Field(validation_alias=AliasChoices("close", "c", "price"))
    volume: int = Field(validation_alias=AliasChoices("volume", "v", "lot"))
    value: Decimal | None = Field(
        default=None, validation_alias=AliasChoices("value", "value_traded")
    )
    freq: int | None = Field(default=None, validation_alias=AliasChoices("frequency", "freq"))

    @field_validator("ts")
    @classmethod
    def naive_source_time_is_jakarta(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=ZoneInfo("Asia/Jakarta")) if value.tzinfo is None else value


def parse_source_candle(raw: JsonValue) -> Candle:
    try:
        row = SourceCandle.model_validate(raw)
    except ValidationError as exc:
        raise CandleDataError("Invalid or incomplete upstream candle row") from exc
    return Candle(row.ts, row.open, row.high, row.low, row.close, row.volume, row.value, row.freq)
