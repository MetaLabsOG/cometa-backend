import asyncio
import logging

from api.stats import get_lp_price
from blockchain.assets import MICROALGOS_IN_ALGO
from blockchain.indexer import get_asset, get_address_app_ids
from blockchain.node import get_current_round
from core.db.contracts import get_contracts
from core.db.pools import pools_db
from core.js_interop import calljs
from core.db.model import ContractInfo, PoolState, UserPool, PoolType
from core.tinychart import get_asset_price, get_algo_price
from core.util import strip_version, parse_bignum, blocks_to_seconds, BLOCKS_IN_A_YEAR

# ffs
BIG_NUM = 1000000000000000000

logger = logging.getLogger(__name__)


def get_pool_state(contract: ContractInfo) -> PoolState:
    metadata = contract.metadata
    cache = metadata['cache']
    total_microtokens = parse_bignum(cache['global']['totalStaked'])
    additional = {}

    if contract.type == 'farm' and ('asset_1_id' in metadata or 'asset1_id' in metadata):
        type = PoolType.FARM
        asset_id = parse_bignum(cache['initial']['stakeToken'])
    elif contract.type == 'farm':
        asset_id = parse_bignum(cache['initial']['stakeToken'])
        type = PoolType.STAKING
    else:
        asset_id = parse_bignum(cache['initial']['token'])
        type = PoolType.DISTRIBUTION

    if total_microtokens == 0:
        total_cost = 0
    elif contract.type == 'farm' and ('asset_1_id' in metadata or 'asset1_id' in metadata):
        # different metadata format...
        if 'asset_1_id' in metadata:
            asset1_id = int(metadata['asset_1_id'])
            asset2_id = int(metadata['asset_2_id'])
        else:
            asset1_id = int(metadata['asset1_id'])
            asset2_id = int(metadata['asset2_id'])

        additional['asset1_id'] = asset1_id
        additional['asset2_id'] = asset2_id

        total_tokens = total_microtokens / (10 ** 6)  # TODO: fix not all lp tokens have 6 decimals
        lp_price = get_lp_price(asset1_id, asset2_id)
        total_cost = total_tokens * lp_price
    else:
        asset_info = get_asset(asset_id)
        total_tokens = total_microtokens / (10 ** asset_info['params']['decimals'])
        asset_price = get_asset_price(asset_id)
        total_cost = total_tokens * asset_price

    start_block = parse_bignum(cache['initial']['beginBlock'])
    end_block = parse_bignum(cache['initial']['endBlock'])
    length_blocks = end_block - start_block + 1

    if 'totalRewardAmount' in cache['initial']:
        total_rewards = parse_bignum(cache['initial']['totalRewardAmount'])
        total_algo_rewards = parse_bignum(cache['initial']['totalAlgoRewardAmount'])
        reward_per_block = total_rewards // length_blocks
        algo_reward_per_block = total_algo_rewards // length_blocks
    else:
        reward_per_block = parse_bignum(cache['initial']['rewardPerBlock'])
        algo_reward_per_block = parse_bignum(cache['initial']['extraAlgoRewardPerBlock'])
        total_rewards = reward_per_block * length_blocks
        total_algo_rewards = algo_reward_per_block * length_blocks

    reward_token_field_name = 'rewardToken' if contract.type == 'farm' else 'token'
    reward_token_id = parse_bignum(cache['initial'][reward_token_field_name])
    logger.debug(f'reward_id = {reward_token_id}')
    reward_asset_info = get_asset(reward_token_id)
    reward_asset_price = get_asset_price(reward_token_id)

    total_reward_token_usd = total_rewards / (10 ** reward_asset_info['params']['decimals']) * reward_asset_price
    logger.debug(f'total_reward_usd = {total_reward_token_usd}')

    total_algo_rewards_usd = total_algo_rewards / (10 ** 6) * get_algo_price()
    logger.debug(f'total_algo_reward_usd = {total_algo_rewards_usd}')
    total_rewards_usd = total_reward_token_usd + total_algo_rewards_usd

    current_apr = total_rewards_usd / total_cost * 100 * BLOCKS_IN_A_YEAR / length_blocks if total_cost > 0 else 0

    return PoolState(
        type=type,
        stake_token_id=asset_id,
        total_staked=total_microtokens,
        total_staked_usd=total_cost,
        reward_token_id=reward_token_id,
        total_rewards=total_rewards,
        total_algo_rewards=total_algo_rewards,
        start_block=start_block,
        end_block=end_block,
        lock_length_blocks=parse_bignum(cache['initial']['lockLengthBlocks']),
        reward_per_block=reward_per_block,
        last_update_block=parse_bignum(cache['global']['lastUpdateBlock']),
        reward_per_token_stored=parse_bignum(cache['global']['rewardPerTokenStored']),
        length_blocks=length_blocks,
        algo_reward_per_block=algo_reward_per_block,
        current_apr=current_apr,
        additional_info=additional
    )


async def get_local_states_for_type(type: str, address: str, contracts: list[ContractInfo]) -> dict:
    contracts = list(filter(lambda c: c.type == type, contracts))
    if len(contracts) == 0:
        return {}

    ids_and_versions = [{'id': info.id, 'version': strip_version(info.version)} for info in contracts]
    local_states = await calljs('fetchContractsLocalViews',
                                contractType=type,
                                idVersions=ids_and_versions,
                                walletAddress=address)
    return local_states


async def get_local_states(contracts: list[ContractInfo], address: str) -> dict:
    farm_states = get_local_states_for_type('farm', address, contracts)
    distr_states = get_local_states_for_type('distribution', address, contracts)
    list_of_states = await asyncio.gather(farm_states, distr_states)
    res = {}
    for states in list_of_states:
        res.update(states)
    return res


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


async def fetch_user_pools(address: str) -> list[UserPool]:
    all_contracts = get_contracts({'type': {'$in': ['farm', 'distribution']}})
    app_ids = get_address_app_ids(address)
    contracts = list(filter(lambda contract: contract.id in app_ids, all_contracts))
    logger.debug(f'{address} contract_ids = {[c.id for c in contracts]}')

    local_states = await get_local_states(contracts, address)
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

            staked_usd = pool_state.total_staked_usd * staked / pool_state.total_staked

            staked_asset = get_asset(pool_state.stake_token_id)
            staked_tokens = staked / (10 ** staked_asset['params']['decimals'])

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
                pool_state.current_apr,
                staked_usd,
                reward_usd,
                lock_timestamp,
                ended_duration,
                staked_token_id=pool_state.stake_token_id,
                staked_tokens=staked_tokens,
                reward_token_id=pool_state.reward_token_id,
                reward_tokens=reward_tokens
            ))
        except Exception as e:
            logger.error(f'Failed to get info for pool {pool_id}')
            logger.exception(e, exc_info=True)

    return pools


def calculate_tvl_for_type(type: str) -> float:
    pools = pools_db.get_many({'type': type})
    res = 0
    for pool in pools:
        res += pool.staked_usd
    return res
