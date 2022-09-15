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
from core.util import parse_bignum
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


@dataclass
class PoolState:
    microtokens_staked: int
    total_cost_usd: float
    reward_token_id: int
    end_block: int
    lock_length_blocks: int


def get_pool_state(contract: ContractInfo) -> PoolState:
    metadata = contract.metadata
    cache = metadata['cache']
    total_microtokens = parse_bignum(cache['global']['totalStaked'])
    if contract.type == 'farm' and 'asset_1_id' in metadata:  # TODO: refactor metadata to have different classes
        total_tokens = total_microtokens / (10 ** 6)  # TODO: fix not all lp tokens have 6 decimals
        lp_price = get_lp_price(metadata['asset_1_id'], metadata['asset_2_id'])
        total_cost = total_tokens * lp_price
    else:
        if contract.type == 'farm':  # TODO: ну это technical debt, рефачить метадату срочно promptly
            asset_id_field_name = 'stakeToken'
        else:
            asset_id_field_name = 'token'
        asset_id = parse_bignum(cache['initial'][asset_id_field_name])
        asset_info = get_asset(asset_id)
        total_tokens = total_microtokens / (10 ** asset_info['params']['decimals'])
        asset_price = get_asset_price(asset_id)
        total_cost = total_tokens * asset_price

    reward_token_field_name = 'rewardToken' if contract.type == 'farm' else 'token'
    return PoolState(
        total_microtokens,
        total_cost,
        reward_token_id=parse_bignum(cache['initial'][reward_token_field_name]),
        end_block=parse_bignum(cache['initial']['endBlock']),
        lock_length_blocks=parse_bignum(cache['initial']['lockLengthBlocks'])
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
