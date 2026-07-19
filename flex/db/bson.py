"""Lossless BSON codecs for Algorand integer domains."""

from decimal import Decimal
from typing import Any

from bson import Decimal128

ALGORAND_UINT64_MAX = 2**64 - 1


def _decode_integral_decimal(value: object, *, signed: bool) -> int:
    decimal_value = value.to_decimal() if isinstance(value, Decimal128) else Decimal(str(value))
    if not decimal_value.is_finite() or decimal_value != decimal_value.to_integral_value():
        raise ValueError("on-chain amount must be a finite integer")
    parsed = int(decimal_value)
    minimum = -ALGORAND_UINT64_MAX if signed else 0
    if not minimum <= parsed <= ALGORAND_UINT64_MAX:
        raise ValueError("on-chain amount is outside the Algorand uint64 range")
    return parsed


def decode_bson_uint64(value: object) -> int:
    return _decode_integral_decimal(value, signed=False)


def decode_bson_delta(value: object) -> int:
    return _decode_integral_decimal(value, signed=True)


def decode_optional_bson_uint64(value: object | None) -> int | None:
    return None if value is None else decode_bson_uint64(value)


def encode_bson_integer(value: int) -> Decimal128:
    return Decimal128(Decimal(value))


def encode_optional_bson_uint64(
    value: int | None,
) -> Decimal128 | None:
    return None if value is None else encode_bson_integer(value)


def encode_uint64_query_value(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool):
        return encode_bson_integer(value)
    if isinstance(value, list):
        return [encode_uint64_query_value(item) for item in value]
    if isinstance(value, dict):
        return {operator: encode_uint64_query_value(operand) for operator, operand in value.items()}
    return value
