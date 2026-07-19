"""Persistence model for crash-safe outbound Algorand transfers."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from dataclasses_json import config, dataclass_json

from flex.db.bson import (
    decode_bson_uint64,
    decode_optional_bson_uint64,
    encode_bson_integer,
    encode_optional_bson_uint64,
)
from flex.db.classes.base_entity import BaseEntity
from flex.db.classes.bson_uint64 import BsonUint64StorageMixin
from flex.domain.algorand import require_algorand_uint64


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass_json
@dataclass
class AssetTransferIntent(
    BsonUint64StorageMixin,
    BaseEntity["AssetTransferIntent"],
):
    """A signed transaction persisted before its first broadcast attempt."""

    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "first_valid_round",
            "last_valid_round",
            "confirmed_round",
        }
    )

    id: str
    receiver: str
    asset_id: str
    amount_micros: str
    note: str | None
    signed_transaction: str
    txid: str
    first_valid_round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    last_valid_round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    status: str

    attempt_count: int = 0
    confirmed_round: int | None = field(
        default=None,
        metadata=config(
            encoder=encode_optional_bson_uint64,
            decoder=decode_optional_bson_uint64,
        ),
    )
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
        self.first_valid_round = require_algorand_uint64(
            self.first_valid_round,
            "first_valid_round",
        )
        self.last_valid_round = require_algorand_uint64(
            self.last_valid_round,
            "last_valid_round",
        )
        if self.first_valid_round > self.last_valid_round:
            raise ValueError("first_valid_round cannot exceed last_valid_round")
        if self.confirmed_round is not None:
            self.confirmed_round = require_algorand_uint64(
                self.confirmed_round,
                "confirmed_round",
            )

    @property
    def amount_micros_int(self) -> int:
        return int(self.amount_micros)

    @property
    def asset_id_int(self) -> int:
        return int(self.asset_id)
