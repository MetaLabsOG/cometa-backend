from dataclasses import dataclass
from enum import Enum
from typing import Optional

from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class ContractInfo:
    type: str
    id: int
    version: str
    deployed_timestamp: float
    description: str
    metadata: Optional[dict] = None


@dataclass
class UserPool:
    pool_id: int
    name: str
    current_apr: float
    staked_usd: float
    reward_usd: float
    lock_timestamp: int
    ended_duration: Optional[float]

    def needs_compound(self) -> bool:
        return self.reward_usd / self.staked_usd > 0.01 if self.staked_usd > 0 else False

    def is_ended(self) -> bool:
        return self.ended_duration is not None


class PoolType(str, Enum):
    FARM = 'farm'
    DISTRIBUTION = 'distribution'
    STAKING = 'staking'

    def __str__(self):
        return self.value


@dataclass
class PoolState:
    type: PoolType
    stake_token_id: int
    total_staked: int
    reward_token_id: int

    total_staked_usd: float
    additional_info: dict

    total_rewards: int
    total_algo_rewards: int
    reward_per_block: int
    algo_reward_per_block: int

    current_apr: float

    start_block: int
    end_block: int
    length_blocks: int
    lock_length_blocks: int

    last_update_block: int
    reward_per_token_stored: int


class PoolStatus(str, Enum):
    LIVE = 'live'
    ENDED = 'ended'
    UPCOMING = 'upcoming'

    def __str__(self):
        return self.value

    @classmethod
    def from_current_block(cls, current_block: int, start_block: int, end_block: int) -> 'PoolStatus':
        if current_block < start_block:
            return PoolStatus.UPCOMING
        if current_block > end_block:
            return PoolStatus.ENDED
        return PoolStatus.LIVE


@dataclass_json
@dataclass
class PoolInfo:
    id: int
    type: PoolType
    name: str
    stake_token_id: int
    additional_algo_rewards: bool
    reward_token_id: int
    additional_info: dict

    staked: int
    staked_usd: float
    current_apr: float
    status: PoolStatus
