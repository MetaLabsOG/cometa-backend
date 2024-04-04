from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from dataclasses_json import dataclass_json

from flex.blockchain import AssetInfo, ALGO_ASSET_INFO
from flex.db.classes.base_entity import BaseEntity
from flex.db.util import get_uuid


class PoolType(str, Enum):
    STAKING = 'staking'
    FARMING = 'farming'
    ANY = 'any'


@dataclass_json
@dataclass
class PoolInfo:
    id: int
    type: PoolType
    description: str
    address: str

    stake_token: AssetInfo
    reward_token: AssetInfo

    reward_amount_micros: int
    reward_amount: float
    algo_reward_amount_micros: int
    algo_reward_amount: float

    begin_block: int
    end_block: int
    lock_length_blocks: int

    deploy_date: datetime
    begin_date: datetime
    end_date: datetime

    @property
    def length_blocks(self) -> int:
        return self.end_block - self.begin_block


@dataclass_json
@dataclass
class StakingPool(BaseEntity['StakingPool']):
    description: str
    address: str

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

    def to_info(self) -> PoolInfo:
        return PoolInfo(
            id=self.id,
            type=PoolType.STAKING,
            description=self.description,
            address=self.address,
            stake_token=self.stake_token,
            reward_token=self.reward_token,
            reward_amount_micros=self.reward_amount_micros,
            reward_amount=self.stake_token.micros_to_amount(self.reward_amount_micros),
            algo_reward_amount_micros=self.algo_reward_amount_micros,
            algo_reward_amount=ALGO_ASSET_INFO.micros_to_amount(self.algo_reward_amount_micros),
            begin_block=self.begin_block,
            end_block=self.end_block,
            lock_length_blocks=self.lock_length_blocks,
            deploy_date=self.deploy_date,
            begin_date=self.begin_date,
            end_date=self.end_date
        )


@dataclass_json
@dataclass
class FarmingPool(BaseEntity['FarmingPool']):
    description: str
    address: str

    stake_token: AssetInfo
    reward_token: AssetInfo

    first_token: AssetInfo
    second_token: AssetInfo
    dex_name: str

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

    def to_info(self) -> PoolInfo:
        return PoolInfo(
            id=self.id,
            type=PoolType.FARMING,
            description=self.description,
            address=self.address,
            stake_token=self.stake_token,
            reward_token=self.reward_token,
            reward_amount_micros=self.reward_amount_micros,
            reward_amount=self.reward_token.micros_to_amount(self.reward_amount_micros),
            algo_reward_amount_micros=self.algo_reward_amount_micros,
            algo_reward_amount=ALGO_ASSET_INFO.micros_to_amount(self.algo_reward_amount_micros),
            begin_block=self.begin_block,
            end_block=self.end_block,
            lock_length_blocks=self.lock_length_blocks,
            deploy_date=self.deploy_date,
            begin_date=self.begin_date,
            end_date=self.end_date
        )


@dataclass_json
@dataclass
class TxInfo:
    id: str
    confirmed_round: int


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity['PoolTransaction']):
    # TODO: remove one of the fields
    pool_id: int
    pool_address: str
    user_address: str
    asa_id: int
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
    type: PoolType
    stake_token: AssetInfo
    address: str

    total_staked_micros: int
    total_staked: float
    staked_micros_by_address: dict[str, int] = field(default_factory=dict)
    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class PoolState(BaseEntity['PoolState']):
    pool_id: int
    type: PoolType
    stake_token: AssetInfo
    address: str

    staked_micros_by_address: dict[str, int] = field(default_factory=dict)
    total_staked_micros: int = 0
    last_tx: TxInfo | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    @property
    def last_tx_id(self) -> str | None:
        if self.last_tx is None:
            return None
        return self.last_tx.id

    @property
    def total_staked(self) -> float:
        return self.stake_token.micros_to_amount(self.total_staked_micros)

    def to_info(self) -> PoolStateInfo:
        return PoolStateInfo(
            pool_id=self.pool_id,
            type=self.type,
            stake_token=self.stake_token,
            address=self.address,
            staked_micros_by_address=self.staked_micros_by_address,
            total_staked_micros=self.total_staked_micros,
            total_staked=self.stake_token.micros_to_amount(self.total_staked_micros),
            last_tx=self.last_tx
        )


@dataclass_json
@dataclass
class UserPoolStateInfo:
    pool_id: int
    stake_token_id: int
    staked_amount_micros: int
    staked_amount: float
    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class UserStateInfo:
    address: str
    pool_by_address: dict[str, UserPoolStateInfo]
    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class UserPoolState:
    pool_id: int
    stake_token: AssetInfo
    staked_amount_micros: int = 0
    last_tx: TxInfo | None = None

    @property
    def staked_amount(self):
        return self.stake_token.micros_to_amount(self.staked_amount_micros)

    def to_info(self) -> UserPoolStateInfo:
        return UserPoolStateInfo(
            pool_id=self.pool_id,
            stake_token_id=self.stake_token.id,
            staked_amount_micros=self.staked_amount_micros,
            staked_amount=self.staked_amount,
            last_tx=self.last_tx
        )


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str
    pool_by_address: dict[str, UserPoolState] = field(default_factory=dict)
    last_tx: TxInfo | None = None
    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> UserStateInfo:
        return UserStateInfo(
            address=self.address,
            pool_by_address={pool_address: pool_state.to_info() for pool_address, pool_state in self.pool_by_address.items()},
            last_tx=self.last_tx
        )


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
class LPToken(BaseEntity['LPToken']):
    asset1_id: int
    asset2_id: int
    name: str
    dex: str

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


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
class SyncState(BaseEntity['SyncState']):
    last_round: int | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class SyncBlock(BaseEntity['SyncBlock']):
    round: int
    timestamp: int
    pool_tx_ids: list[str] = field(default_factory=list)

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
