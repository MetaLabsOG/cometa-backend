"""Persistence model for crash-safe outbound Algorand transfers."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass_json
@dataclass
class AssetTransferIntent(BaseEntity["AssetTransferIntent"]):
    """A signed transaction persisted before its first broadcast attempt."""

    id: str
    receiver: str
    asset_id: str
    amount_micros: str
    note: str | None
    signed_transaction: str
    txid: str
    first_valid_round: int
    last_valid_round: int
    status: str

    attempt_count: int = 0
    confirmed_round: int | None = None
    last_error: str | None = None
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    created: datetime = field(default_factory=_utc_now)
    updated: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        # Legacy BSON documents may contain int64 values; new writes stay
        # string-backed so the full Algorand uint64 domain is lossless.
        self.asset_id = str(self.asset_id)
        self.amount_micros = str(self.amount_micros)

    @property
    def amount_micros_int(self) -> int:
        return int(self.amount_micros)

    @property
    def asset_id_int(self) -> int:
        return int(self.asset_id)
