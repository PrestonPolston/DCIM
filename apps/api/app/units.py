"""Length input in mm or inches (ADMIN_INPUT_PLAN rev 3 §4c). Storage and responses are always mm.

A request body may carry ``"unit": "mm" | "in"`` (default mm); it applies to every ``*_mm`` field of that body.
Inches convert as ``mm = in × 25.4`` and round half-up: to whole mm for INT columns (cabinet profiles) and to
0.1 mm for Numeric columns (device profiles). Range checks run on the converted mm value.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from typing import ClassVar, Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

MM_PER_IN = Decimal("25.4")
UNITS = ("mm", "in")


def to_mm(value, unit: str, step: str):
    """Convert one value; ``step`` "1" -> int mm, "0.1" -> float mm. Non-numbers pass through for normal validation."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return value
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return value
    if not d.is_finite():
        return value
    if unit == "in":
        d = d * MM_PER_IN
        try:
            q = d.quantize(Decimal(step), rounding=ROUND_HALF_UP)
        except InvalidOperation:  # too many digits to round: far beyond any column range
            raise PydanticCustomError("invalid_dimension", "Value is too large to store") from None
        return int(q) if step == "1" else float(q)
    return value


UnitLiteral = Literal["mm", "in"]


def unit_field():
    """Documented in OpenAPI; consumed (popped) by UnitInput before validation, never stored or returned."""
    return Field(None, exclude=True, description="Unit of every *_mm length in this body: mm (default) or in. "
                 "Stored and returned in mm; inches round half-up")


class UnitInput:
    """Mixin for InputModel bodies: pops ``unit`` and converts the listed mm fields before validation."""
    MM_FIELDS: ClassVar[tuple[str, ...]] = ()
    MM_STEP: ClassVar[str] = "1"

    @model_validator(mode="before")
    @classmethod
    def _convert_units(cls, data):
        if not isinstance(data, dict) or "unit" not in data:
            return data
        data = dict(data)
        unit = data.pop("unit")
        if unit is None:
            return data
        if unit not in UNITS:
            raise PydanticCustomError("invalid_unit", "unit must be 'mm' or 'in'")
        for f in cls.MM_FIELDS:
            if f in data:
                data[f] = to_mm(data[f], unit, cls.MM_STEP)
        return data
