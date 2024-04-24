from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.model.pool_states import PoolStateInfo
from flex.db.model.pools import PoolInfo
from flex.db.util import get_uuid


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
class AirdropReward(BaseEntity['AirdropReward']):
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
    price_usd: float
    price_algo: float
    last_update_round: int
    seconds_since_update: int


@dataclass_json
@dataclass
class AssetPrice(BaseEntity['AssetPrice']):
    id: int
    price_usd: float
    price_algo: float
    last_update_round: int

    # TODO: remove after migration
    name: str | None = None
    tinyman_algo_pool_id: int | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self, current_time: datetime) -> AssetPriceInfo:
        seconds_since_update = (current_time - self.updated).total_seconds()
        return AssetPriceInfo(
            asset_id=self.id,
            price_usd=self.price_usd,
            price_algo=self.price_algo,
            last_update_round=self.last_update_round,
            seconds_since_update=int(seconds_since_update)
        )
