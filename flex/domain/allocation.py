"""Exact, deterministic allocation of integer asset base units."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from fractions import Fraction

type ShareInput = Decimal | int | float | str

MAX_SHARE_EXPONENT = 300
MAX_SHARE_SIGNIFICANT_DIGITS = 50


class AllocationError(ValueError):
    """Raised when an allocation cannot preserve its financial invariants."""


def _positive_decimal(value: ShareInput, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise AllocationError(f"{field} must be numeric, not bool")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AllocationError(f"{field} is not a valid decimal") from exc

    if not parsed.is_finite():
        raise AllocationError(f"{field} must be finite")
    if parsed <= 0:
        raise AllocationError(f"{field} must be positive")
    if abs(parsed.adjusted()) > MAX_SHARE_EXPONENT:
        raise AllocationError(f"{field} exponent is outside the supported range")
    if len(parsed.as_tuple().digits) > MAX_SHARE_SIGNIFICANT_DIGITS:
        raise AllocationError(f"{field} has too many significant digits")
    return parsed


def allocate_proportionally(
    total_micros: int,
    shares: Mapping[str, ShareInput],
) -> dict[str, int]:
    """Allocate an integer budget exactly using the largest-remainder method.

    Fractional remainders are resolved by recipient ID, making the result
    reproducible regardless of mapping insertion order.
    """

    if isinstance(total_micros, bool) or not isinstance(total_micros, int):
        raise AllocationError("total_micros must be an integer")
    if total_micros <= 0:
        raise AllocationError("total_micros must be positive")
    if not shares:
        raise AllocationError("shares must not be empty")

    weights: dict[str, Fraction] = {}
    for recipient, share in shares.items():
        if not isinstance(recipient, str) or not recipient.strip():
            raise AllocationError("recipient IDs must be non-empty strings")
        parsed = _positive_decimal(share, field=f"shares[{recipient!r}]")
        weights[recipient] = Fraction(parsed)

    total_weight = sum(weights.values(), start=Fraction())
    allocations: dict[str, int] = {}
    remainders: list[tuple[Fraction, str]] = []

    for recipient in sorted(weights):
        exact_amount = Fraction(total_micros) * weights[recipient] / total_weight
        floor_amount = exact_amount.numerator // exact_amount.denominator
        allocations[recipient] = floor_amount
        remainders.append((exact_amount - floor_amount, recipient))

    undistributed = total_micros - sum(allocations.values())
    ranked_remainders = sorted(
        remainders,
        key=lambda item: (-item[0], item[1]),
    )
    for _, recipient in ranked_remainders[:undistributed]:
        allocations[recipient] += 1

    if sum(allocations.values()) != total_micros:
        raise AssertionError("allocation must preserve the integer budget")
    return allocations
