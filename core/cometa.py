import logging
from dataclasses import dataclass
from typing import Optional, List

from api.stats import get_pool_state, PoolState
from blockchain.assets import MICROALGOS_IN_ALGO
from blockchain.indexer import get_asset
from blockchain.node import get_current_round
from core.contract_manager import get_contracts
from core.js_interop import calljs
from core.tinychart import get_asset_price, get_algo_price
from core.util import strip_version, parse_bignum, blocks_to_seconds, YEAR_SECONDS, BLOCK_TIME


# ffs
BIG_NUM = 1000000000000000000

logger = logging.getLogger(__name__)


@dataclass
class UserPool:
    pool_id: int
    name: str
    staked_usd: float
    reward_usd: float
    lock_timestamp: int
    ended_duration: Optional[float]


async def get_local_states(type: str, address: str) -> dict:
    contracts = get_contracts({'type': type})
    if not contracts:
        return {}
    ids_and_versions = [{'id': info.id, 'version': strip_version(info.version)} for info in contracts]
    local_states = await calljs("fetchContractsLocalViews",
                                contractType=type,
                                idVersions=ids_and_versions,
                                walletAddress=address)
    return local_states


def recalculate_reward(pool: PoolState, current_block: int, staked: int, reward: int,
                       reward_per_token_paid: int) -> int:
    if pool.last_update_block >= current_block or pool.total_staked == 0 or staked == 0:
        return reward

    last_block_with_rewards = min(current_block, pool.end_block)
    reward_blocks_passed = last_block_with_rewards - pool.last_update_block
    reward_per_token_stored_new = pool.reward_per_token_stored + \
                                  reward_blocks_passed * pool.reward_per_block * BIG_NUM // pool.total_staked
    reward_to_pay_now = staked * (reward_per_token_stored_new - reward_per_token_paid) // BIG_NUM
    return reward + reward_to_pay_now


async def get_user_pools(address: str) -> List[UserPool]:
    local_states = await get_local_states('farm', address) | await get_local_states('distribution', address)
    all_contracts = get_contracts({'type': {'$in': ['farm', 'distribution']}})
    contract_by_id = {str(c.id): c for c in all_contracts}
    pools = []
    for pool_id, state in local_states.items():
        try:
            reward = parse_bignum(state['reward'])
            staked = parse_bignum(state['staked'])

            # user doesn't have interest in such pools
            if reward == 0 and staked == 0:
                continue

            lock_timestamp = parse_bignum(state['lockTimestamp'])

            contract = contract_by_id[str(pool_id)]
            pool_state = get_pool_state(contract)

            current_block = get_current_round()
            ended_duration = None
            if current_block > pool_state.end_block:
                ended_duration = blocks_to_seconds(pool_state.end_block, current_block)

            staked_usd = pool_state.total_cost_usd * staked / pool_state.total_staked

            logger.debug(contract.description)
            logger.debug(contract.id)

            reward_per_token_paid = parse_bignum(state['rewardPerTokenPaid'])
            reward = recalculate_reward(pool_state, current_block, staked, reward, reward_per_token_paid)

            reward_asset = get_asset(pool_state.reward_token_id)
            reward_tokens = reward / (10 ** reward_asset['params']['decimals'])

            reward_price = get_asset_price(pool_state.reward_token_id)
            reward_usd = reward_tokens * reward_price

            reward_usd += reward * pool_state.total_algo_rewards // \
                          pool_state.total_rewards * get_algo_price() / MICROALGOS_IN_ALGO

            pools.append(UserPool(
                pool_id,
                contract.description,
                staked_usd,
                reward_usd,
                lock_timestamp,
                ended_duration
            ))
        except Exception as e:
            logger.error(f'Failed to get info for pool {pool_id}')
            logger.exception(e, exc_info=True)

    return pools


@dataclass
class PoolInfo:
    name: str
    id: int
    staked_usd: float
    current_apr: float


async def get_live_pools_info() -> List[PoolInfo]:
    all_contracts = get_contracts({'type': {'$in': ['farm', 'distribution']}})
    current_block = get_current_round()
    pools = []
    for contract in all_contracts:
        try:
            pool_state = get_pool_state(contract)
            if pool_state.end_block < current_block or pool_state.start_block > current_block:
                continue

            pools.append(PoolInfo(
                contract.description,
                contract.id,
                pool_state.total_cost_usd,
                pool_state.current_apr
            ))
        except Exception as e:
            logger.error(f'Failed to get info for pool {contract.description}')
            logger.exception(e, exc_info=True)

    return pools
