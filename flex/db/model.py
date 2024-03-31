from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.blockchain import AssetInfo
from flex.db.classes.base_entity import BaseEntity
from flex.db.util import get_uuid


@dataclass_json
@dataclass
class StakingPool(BaseEntity['StakingPool']):
    stake_token: AssetInfo
    reward_token: AssetInfo

    reward_amount_micros: int
    algo_reward_amount_micros: int

    begin_block: int
    end_block: int
    lock_length_blocks: int

    deploy_date: datetime
    begin_date: datetime
    end_date: datetime

    id: int
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class FarmingPool(BaseEntity['FarmingPool']):
    first_token: AssetInfo
    second_token: AssetInfo
    dex_name: str

    lp_token: AssetInfo
    reward_token: AssetInfo

    reward_amount_micros: int
    algo_reward_amount_micros: int

    begin_block: int
    end_block: int
    lock_length_blocks: int

    deploy_date: datetime
    begin_date: datetime
    end_date: datetime

    id: int
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class TxInfo:
    id: str
    confirmed_round: int


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity['PoolTransaction']):
    pool_id: int
    pool_address: str
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
class PoolStateInfo:
    pool_id: int
    stake_token: AssetInfo
    address: str
    staked_amount_micros: int
    staked_amount: float
    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class PoolState(BaseEntity['PoolState']):
    pool_id: int
    stake_token: AssetInfo
    address: str

    staked_amount_micros: int = 0
    last_tx: TxInfo | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    @property
    def last_tx_id(self) -> str | None:
        if self.last_tx is None:
            return None
        return self.last_tx.id

    def to_info(self) -> PoolStateInfo:
        return PoolStateInfo(
            pool_id=self.pool_id,
            stake_token=self.stake_token,
            address=self.address,
            staked_amount_micros=self.staked_amount_micros,
            staked_amount=self.stake_token.micros_to_amount(self.staked_amount_micros),
            last_tx=self.last_tx
        )


@dataclass_json
@dataclass
class UserPoolState:
    pool_id: str

    stake_token: AssetInfo
    staked_amount_micros: int = 0

    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str

    pool_by_id: dict[int, UserPoolState] = field(default_factory=dict)
    last_tx: TxInfo | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
