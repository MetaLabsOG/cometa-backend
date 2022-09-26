import logging
import time
import traceback
from dataclasses import dataclass
from typing import Optional

from cachetools import cached, TTLCache, FIFOCache
from dataclasses_json import dataclass_json

from core import mongodb
from core.contract_manager import get_contracts_by_type, ContractInfo
from core.tinychart import get_asset_price
from blockchain.indexer import get_asset
from blockchain.node import init_algod_client
from core.util import parse_bignum, BLOCKS_IN_A_YEAR
from dexes.tinyman import init_tinyman_client, get_pool_info
from env import settings


@dataclass_json
@dataclass
class CometaSnapshot:
    farm_tvl: float
    distribution_tvl: float
    timestamp: float


tiny_client = init_tinyman_client(settings.algod_address)
algod = init_algod_client()
snapshots = mongodb.database.snapshot

logger = logging.getLogger(__name__)


def save_snapshot(farm_tvl: float, distribution_tvl: float) -> CometaSnapshot:
    cur_time = time.time()
    snapshot = CometaSnapshot(farm_tvl, distribution_tvl, cur_time)
    snapshots.insert_one(snapshot.to_dict())
    return snapshot


def get_last_snapshot() -> Optional[CometaSnapshot]:
    res = snapshots.find().limit(1).sort("$natural", -1).next()
    return CometaSnapshot.from_dict(res) if res else res


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_lp_price(asset1_id: int, asset2_id: int) -> float:
    pool = get_pool_info(tiny_client, asset1_id, asset2_id)
    price1 = get_asset_price(asset1_id)
    price2 = get_asset_price(asset2_id)
    total_cost = price1 * pool.asset1_reserve + price2 * pool.asset2_reserve
    lp_price = total_cost / pool.total_lp_tokens
    return lp_price


@cached(cache=FIFOCache(maxsize=1024))
def get_asset_info(asset_id: int) -> dict:
    return tiny_client.fetch_asset(asset_id)


# TODO: move to cometa package
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


def get_pool_state(contract: ContractInfo) -> PoolState:
    metadata = contract.metadata
    cache = metadata['cache']
    total_microtokens = parse_bignum(cache['global']['totalStaked'])
    if contract.type == 'farm' and 'asset_1_id' in metadata:  # TODO: refactor metadata to have different classes
        total_tokens = total_microtokens / (10 ** 6)  # TODO: fix not all lp tokens have 6 decimals
        lp_price = get_lp_price(metadata['asset_1_id'], metadata['asset_2_id'])
        total_cost = total_tokens * lp_price
    else:
        if contract.type == 'farm':  # TODO: ну это пиздец, рефачить метадату срочно нахуй
            asset_id_field_name = 'stakeToken'
        else:
            asset_id_field_name = 'token'
        asset_id = parse_bignum(cache['initial'][asset_id_field_name])
        asset_info = get_asset(asset_id)
        total_tokens = total_microtokens / (10 ** asset_info['params']['decimals'])
        logger.debug(f'{contract.description} = {asset_id}')
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
    reward_asset_info = get_asset(reward_token_id)
    reward_asset_price = get_asset_price(reward_token_id)
    total_reward_token_usd = total_rewards / (10 ** reward_asset_info['params']['decimals']) * reward_asset_price
    total_algo_rewards_usd = total_algo_rewards / (10 ** 6) * get_asset_price(0)
    total_rewards_usd = total_reward_token_usd + total_algo_rewards_usd

    current_apr = total_rewards_usd / total_cost * 100 * BLOCKS_IN_A_YEAR * length_blocks

    return PoolState(
        total_staked=total_microtokens,
        total_cost_usd=total_cost,
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
        current_apr=current_apr
    )


def calculate_tvl_for_type(type: str) -> float:
    contracts = get_contracts_by_type(type)
    res = 0
    for contract in contracts:
        try:
            pool_state = get_pool_state(contract)
            res += pool_state.total_cost_usd
        except Exception:
            logger.error(f'Exception for {contract.description}')
            logger.error(traceback.print_exc(), '\n')
    return res


@cached(cache=TTLCache(maxsize=1, ttl=settings.total_tvl_ttl))
def get_tvl() -> dict:
    snapshot = get_last_snapshot()
    return {
        'farm': snapshot.farm_tvl,
        'distribution': snapshot.distribution_tvl,
        'total': snapshot.farm_tvl + snapshot.distribution_tvl
    }
