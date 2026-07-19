from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from dataclasses_json import config, dataclass_json

from flex.db.bson import (
    decode_bson_delta,
    decode_bson_uint64,
    encode_bson_integer,
)
from flex.db.classes.base_entity import BaseEntity
from flex.db.classes.bson_uint64 import BsonUint64StorageMixin
from flex.domain.algorand import MAX_ALGORAND_UINT, require_algorand_uint64
from flex.domain.lp_projection import InvalidLpProjectionError, lp_event_order


@dataclass_json
@dataclass
class LpStateInfo:
    id: int
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    issued_tokens_micros: int

    asset1_reserve: float
    asset2_reserve: float
    issued_tokens: float

    token_price_algo: float
    token_price_usd: float

    last_updated_round: int
    swap_fee_apr: float | None = None
    seconds_since_update: int | None = None


@dataclass_json
@dataclass
class LpState(
    BsonUint64StorageMixin,
    BaseEntity["LpState"],
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "token_id",
            "asset1_id",
            "asset2_id",
            "last_updated_round",
            "asset1_reserve_micros",
            "asset2_reserve_micros",
            "total_tokens_micros",
            "operational_algo_balance_micros",
        }
    )

    id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    token_id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    asset1_id: int = field(  # asset1_id > asset2_id
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    asset2_id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    dex_provider: str
    address: str

    last_updated_round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    # TODO: could not fit into MongoDB ??? (64 bits)
    asset1_reserve_micros: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    asset2_reserve_micros: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    total_tokens_micros: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )

    asset1_reserve: float
    asset2_reserve: float
    total_tokens: float
    token_price_algo: float

    # Token-token pools still hold ALGO to fund network fees. Keep this
    # operational balance separate from economic reserves and public pricing.
    operational_algo_balance_micros: int = field(
        default=0,
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        ),
    )
    is_algo_pool: bool = False
    last_event_order: str | None = None
    derived_observed_at: datetime | None = None

    swap_fee_apr: float | None = None
    updated: datetime = field(default_factory=datetime.now)
    created: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        try:
            for field_name in self.BSON_UINT64_FIELDS:
                require_algorand_uint64(
                    getattr(self, field_name),
                    field_name,
                )
        except ValueError as exc:
            raise InvalidLpProjectionError(str(exc)) from exc

    @classmethod
    def primary_key_name(cls) -> str:
        return "token_id"

    def to_info(self, algo_price_usd: float, current_time: datetime | None = None) -> LpStateInfo:
        current_time = current_time or datetime.now()
        return LpStateInfo(
            id=self.id,
            token_id=self.token_id,
            asset1_id=self.asset1_id,
            asset2_id=self.asset2_id,
            dex_provider=self.dex_provider,
            address=self.address,
            asset1_reserve_micros=self.asset1_reserve_micros,
            asset2_reserve_micros=self.asset2_reserve_micros,
            issued_tokens_micros=self.total_tokens_micros,
            asset1_reserve=self.asset1_reserve,
            asset2_reserve=self.asset2_reserve,
            issued_tokens=self.total_tokens,
            token_price_algo=self.token_price_algo,
            token_price_usd=self.token_price_algo * algo_price_usd,
            last_updated_round=self.last_updated_round,
            swap_fee_apr=self.swap_fee_apr,
            seconds_since_update=int((current_time - self.updated).total_seconds()),
        )


@dataclass_json
@dataclass
class LpTransaction(BaseEntity["LpTransaction"]):
    id: str
    pool_address: str
    user_address: str
    asa_id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    delta_amount_micros: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_delta,
        )
    )
    confirmed_round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )

    event_position: int = field(
        default=0,
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        ),
    )
    event_order: str | None = None
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        try:
            require_algorand_uint64(self.asa_id, "asa_id")
            require_algorand_uint64(self.confirmed_round, "confirmed_round")
            require_algorand_uint64(self.event_position, "event_position")
        except ValueError as exc:
            raise InvalidLpProjectionError(str(exc)) from exc
        if (
            isinstance(self.delta_amount_micros, bool)
            or not isinstance(self.delta_amount_micros, int)
            or not -MAX_ALGORAND_UINT <= self.delta_amount_micros <= MAX_ALGORAND_UINT
        ):
            raise InvalidLpProjectionError(
                "delta_amount_micros must fit the signed Algorand uint64 domain",
            )
        expected_order = lp_event_order(
            self.confirmed_round,
            self.id,
            self.event_position,
        )
        if self.event_order is None:
            self.event_order = expected_order
        elif self.event_order != expected_order:
            raise InvalidLpProjectionError("event_order does not match the immutable event fields")
