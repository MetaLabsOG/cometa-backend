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
from flex.db.model.pool_states import PoolStateInfo
from flex.db.model.pools import PoolInfo
from flex.db.util import get_uuid


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass_json
@dataclass
class PoolStateCost:
    info: PoolStateInfo
    staked_usd: float
    current_apr: float


@dataclass_json
@dataclass
class UserPoolCost:
    pool_info: PoolInfo
    staked_usd: float


@dataclass_json
@dataclass
class UserCost:
    address: str
    total_staked_usd: float = 0
    pools_by_id: dict[int, UserPoolCost] = field(default_factory=dict)


@dataclass_json
@dataclass
class AirdropReward(BaseEntity["AirdropReward"]):
    airdrop_id: str
    address: str
    asa_id: str
    amount_micros: str
    txid: str

    operation_id: str | None = None
    confirmed_round: int | None = field(
        default=None,
        metadata=config(
            encoder=encode_optional_bson_uint64,
            decoder=decode_optional_bson_uint64,
        ),
    )
    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        self.asa_id = str(self.asa_id)
        self.amount_micros = str(self.amount_micros)

    @property
    def asa_id_int(self) -> int:
        return int(self.asa_id)

    @property
    def amount_micros_int(self) -> int:
        return int(self.amount_micros)


@dataclass_json
@dataclass
class AssetPriceInfo:
    asset_id: int
    asset_name: str
    price_usd: float
    price_algo: float
    last_update_round: int
    seconds_since_update: int


@dataclass_json
@dataclass
class AssetPrice(
    BsonUint64StorageMixin,
    BaseEntity["AssetPrice"],
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "last_update_round",
            "tinyman_algo_pool_id",
        }
    )

    id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    price_usd: float
    price_algo: float
    last_update_round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    name: str

    tinyman_algo_pool_id: int | None = field(
        default=None,
        metadata=config(
            encoder=encode_optional_bson_uint64,
            decoder=decode_optional_bson_uint64,
        ),
    )
    source: str | None = None
    observed_at: datetime | None = None

    created: datetime = field(default_factory=_utc_now)
    updated: datetime = field(default_factory=_utc_now)

    def to_info(self, current_time: datetime) -> AssetPriceInfo:
        observation_time = self.observed_at or self.updated
        seconds_since_update = max(
            0,
            int((_as_utc(current_time) - _as_utc(observation_time)).total_seconds()),
        )
        return AssetPriceInfo(
            asset_id=self.id,
            asset_name=self.name,
            price_usd=self.price_usd,
            price_algo=self.price_algo,
            last_update_round=self.last_update_round,
            seconds_since_update=seconds_since_update,
        )
