from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.model.pool_states import PoolStateInfo
from flex.db.model.pools import PoolInfo
from flex.db.util import get_uuid


@dataclass_json
@dataclass
class PricedUserPool:
    id: int

    stake_token_id: int
    stake_token_unit_name: str
    stake_amount: float
    stake_usd: float

    reward_token_id: int
    reward_token_unit_name: str
    reward_amount: float
    reward_usd: float

    total_usd: float
    total_amount: float
    current_apr: float

    updated_round: int


@dataclass_json
@dataclass
class PricedUser:
    address: str
    total_staked_usd: float
    pools_by_id: dict[int, PricedUserPool]
    updated_round: int


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
