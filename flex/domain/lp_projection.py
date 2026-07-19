"""Pure invariants for ordered liquidity-pool projections."""

from dataclasses import dataclass
from typing import Literal

MAX_ALGORAND_UINT = 2**64 - 1
EVENT_ROUND_WIDTH = 20
ROUND_END_SUFFIX = "~"

type LpBalanceField = Literal[
    "asset1_reserve_micros",
    "asset2_reserve_micros",
    "total_tokens_micros",
]


class InvalidLpProjectionError(ValueError):
    """Raised when an LP event cannot safely update its target aggregate."""


@dataclass(frozen=True, slots=True)
class LpBalanceDelta:
    field: LpBalanceField
    amount: int


def lp_event_order(
    confirmed_round: int,
    event_id: str,
    event_position: int = 0,
) -> str:
    """Build a lexicographically sortable, deterministic event cursor."""

    if (
        isinstance(confirmed_round, bool)
        or not isinstance(confirmed_round, int)
        or not 0 <= confirmed_round <= MAX_ALGORAND_UINT
    ):
        raise InvalidLpProjectionError("confirmed_round must be an Algorand uint64")
    if not isinstance(event_id, str) or not event_id or ":" in event_id:
        raise InvalidLpProjectionError("event_id must be non-empty and cannot contain ':'")
    if (
        isinstance(event_position, bool)
        or not isinstance(event_position, int)
        or not 0 <= event_position <= MAX_ALGORAND_UINT
    ):
        raise InvalidLpProjectionError("event_position must be an Algorand uint64")
    return f"{confirmed_round:0{EVENT_ROUND_WIDTH}d}:{event_position:0{EVENT_ROUND_WIDTH}d}:{event_id}"


def lp_round_end_order(confirmed_round: int) -> str:
    """Represent an authoritative snapshot taken after an entire round."""

    prefix = lp_event_order(confirmed_round, "snapshot").partition(":")[0]
    return f"{prefix}:{ROUND_END_SUFFIX}"


def snapshot_covers_event(cursor: str, *, confirmed_round: int) -> bool:
    """Return whether a round-end snapshot is authoritative for an event."""

    round_prefix, separator, suffix = cursor.partition(":")
    return (
        separator == ":"
        and suffix == ROUND_END_SUFFIX
        and len(round_prefix) == EVENT_ROUND_WIDTH
        and round_prefix.isdigit()
        and int(round_prefix) >= confirmed_round
    )


def lp_cursor_complete_through(cursor: str | None) -> int:
    """Return the last round fully covered by a persisted LP cursor."""

    if cursor is None:
        raise InvalidLpProjectionError("LP cursor is missing")
    round_prefix, separator, suffix = cursor.partition(":")
    if separator != ":" or len(round_prefix) != EVENT_ROUND_WIDTH or not round_prefix.isdigit() or not suffix:
        raise InvalidLpProjectionError("LP cursor has an invalid format")
    round_number = int(round_prefix)
    if suffix == ROUND_END_SUFFIX:
        return round_number
    if round_number == 0:
        raise InvalidLpProjectionError("an event cursor in round zero covers no complete round")
    return round_number - 1


def lp_balance_delta(
    *,
    token_id: int,
    asset1_id: int,
    asset2_id: int,
    event_asset_id: int,
    event_pool_delta_micros: int,
) -> LpBalanceDelta:
    """Map one pool-account transfer to its canonical LP balance field."""

    if isinstance(event_pool_delta_micros, bool) or not isinstance(event_pool_delta_micros, int):
        raise InvalidLpProjectionError("event delta must be an integer")
    if not -MAX_ALGORAND_UINT <= event_pool_delta_micros <= MAX_ALGORAND_UINT:
        raise InvalidLpProjectionError("event delta is outside the Algorand uint64 range")

    if event_asset_id == token_id:
        return LpBalanceDelta(
            field="total_tokens_micros",
            amount=-event_pool_delta_micros,
        )
    if event_asset_id == asset1_id:
        return LpBalanceDelta(
            field="asset1_reserve_micros",
            amount=event_pool_delta_micros,
        )
    if event_asset_id == asset2_id:
        return LpBalanceDelta(
            field="asset2_reserve_micros",
            amount=event_pool_delta_micros,
        )
    raise InvalidLpProjectionError(
        f"asset {event_asset_id} does not belong to LP token {token_id}",
    )
