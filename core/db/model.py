import json
from dataclasses import dataclass, field
from datetime import datetime
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
    deployed_date: Optional[datetime] = None
    begin_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    def __post_init__(self):
        if self.deployed_timestamp is not None:
            self.deployed_date = datetime.fromtimestamp(self.deployed_timestamp)

    def without_cache(self) -> 'ContractInfo':
        metadata = dict(self.metadata) if self.metadata is not None else None
        metadata['cache'] = None
        return ContractInfo(
            type=self.type,
            id=self.id,
            version=self.version,
            deployed_timestamp=self.deployed_timestamp,
            description=self.description,
            metadata=metadata,
            deployed_date=self.deployed_date,
            begin_date=self.begin_date,
            end_date=self.end_date
        )

    def format_str(self) -> str:
        return json.dumps(self.to_dict(), indent=4, default=str)


@dataclass_json
@dataclass
class UserPool:
    pool_id: int
    name: str
    current_apr: float
    staked_usd: float
    reward_usd: float
    lock_timestamp: int
    ended_duration: Optional[float]
    staked_token_id: Optional[int] = None  # TODO: remove Optional when all UserPools are migrated
    reward_token_id: Optional[int] = None
    staked_tokens: Optional[float] = None
    reward_tokens: Optional[float] = None
    staked_microtokens: Optional[str] = None
    last_updated: Optional[datetime] = None

    def needs_compound(self) -> bool:
        return self.reward_usd / self.staked_usd > 0.01 if self.staked_usd > 0 else False

    def is_ended(self) -> bool:
        return self.ended_duration is not None


@dataclass_json
@dataclass
class CometaUser:
    address: str
    pools: list[UserPool] = field(default_factory=list)


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

    last_updated: Optional[datetime] = None


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

    lock_length_blocks: Optional[int] = None

    last_updated: Optional[datetime] = None
