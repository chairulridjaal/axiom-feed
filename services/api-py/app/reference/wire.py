"""An exact decompressed-byte receipt accompanies bounded provider JSON."""

from dataclasses import dataclass

from pydantic import JsonValue


@dataclass(frozen=True, slots=True)
class WireJSON:
    data: JsonValue
    byte_count: int
