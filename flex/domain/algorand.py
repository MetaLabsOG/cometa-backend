"""Algorand protocol value boundaries shared by external adapters."""

MAX_ALGORAND_UINT = 2**64 - 1


def require_algorand_uint64(
    value: object,
    field: str,
    *,
    positive: bool = False,
) -> int:
    """Return an exact protocol integer or reject coercible lookalikes."""

    if isinstance(value, bool) or not isinstance(value, int) or value < int(positive) or value > MAX_ALGORAND_UINT:
        requirement = "a positive Algorand uint64" if positive else "an Algorand uint64"
        raise ValueError(f"{field} must be {requirement}")
    return value
