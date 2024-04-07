from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from dataclasses_json import dataclass_json

from flex.blockchain.info import ALGO_ASSET_INFO
from flex.db.model.blockchain import Asset
from flex.db.classes.base_entity import BaseEntity


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

    stake_token: Asset
    reward_token: Asset

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

    stake_token: Asset
    reward_token: Asset
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

    stake_token: Asset
    reward_token: Asset

    first_token: Asset
    second_token: Asset
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
