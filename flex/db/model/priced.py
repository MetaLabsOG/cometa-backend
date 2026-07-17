from dataclasses import dataclass, field
from datetime import UTC, datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
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
    asa_id: int
    amount_micros: int
    txid: str

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


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
class AssetPrice(BaseEntity["AssetPrice"]):
    id: int
    price_usd: float
    price_algo: float
    last_update_round: int
    name: str

    tinyman_algo_pool_id: int | None = None
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
