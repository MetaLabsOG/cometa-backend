from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.util import get_uuid


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
class TxInfo:
    id: str
    confirmed_round: int


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity['PoolTransaction']):
    pool_id: str
    user_address: str
    asa_id: str
    delta_amount_micros: int
    confirmed_round: int
    id: str

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> TxInfo:
        return TxInfo(id=self.id, confirmed_round=self.confirmed_round)


@dataclass_json
@dataclass
class PoolState(BaseEntity['PoolState']):
    pool_id: int
    stake_token_id: int
    address: str

    staked_amount: float = 0
    staked_amount_micros: int = 0

    last_tx: TxInfo | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=get_uuid)

    @property
    def last_tx_id(self) -> str | None:
        if self.last_tx is None:
            return None
        return self.last_tx.id


@dataclass_json
@dataclass
class PoolStateInfo:
    id: str
    stake_token_id: int
    staked_amount: float
    staked_amount_micros: int

    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str
    id: str

    pools: list[PoolStateInfo] = field(default_factory=list)
    last_updated_round: int | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
