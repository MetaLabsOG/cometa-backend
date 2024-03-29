from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from core.new.db.classes.base_entity import BaseEntity


@dataclass_json
@dataclass
class StakingPool(BaseEntity['StakingPool']):
    pass


@dataclass_json
@dataclass
class FarmingPool(BaseEntity['FarmingPool']):
    pass


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity['PoolTransaction']):
    pool_id: str
    user_address: str
    asa_id: str
    delta_amount_micros: int
    confirmed_round: int
    id: str

    created: datetime = field(default_factory=datetime.utcnow)
    updated: datetime = field(default_factory=datetime.utcnow)


@dataclass_json
@dataclass
class PoolStateInfo:
    id: str
    stake_token_id: int
    staked_amount: float
    staked_amount_micros: int

    last_txid: str | None = None
    last_updated_round: int | None = None


@dataclass_json
@dataclass
class PoolState(BaseEntity['PoolState']):
    stake_token_id: int
    address: str
    id: int

    staked_amount: float = 0
    staked_amount_micros: int = 0

    last_txid: str | None = None
    last_updated_round: int | None = None

    created: datetime = field(default_factory=datetime.utcnow)
    updated: datetime = field(default_factory=datetime.utcnow)


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str
    id: str

    pools: list[PoolStateInfo] = field(default_factory=list)
    last_updated_round: int | None = None

    created: datetime = field(default_factory=datetime.utcnow)
    updated: datetime = field(default_factory=datetime.utcnow)
