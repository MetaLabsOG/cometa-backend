from dataclasses import dataclass
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


@dataclass
class PoolState:
    total_staked: int
    total_cost_usd: float
    reward_token_id: int

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
