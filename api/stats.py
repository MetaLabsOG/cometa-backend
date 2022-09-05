import time
import traceback
from dataclasses import dataclass
from typing import Optional

from cachetools import cached, TTLCache, FIFOCache
from dataclasses_json import dataclass_json

from core import mongodb
from core.contract_manager import get_contracts
from core.tinychart import get_asset_price
from blockchain.indexer import get_asset
from blockchain.node import init_algod_client
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


def calculate_tvl_for_type(type: str) -> float:
    contracts = get_contracts(type)
    res = 0
    for contract in contracts:
        try:
            cache = contract.metadata['cache']
            total_microtokens = int(cache['global']['totalStaked']['hex'], 16)
            if type == 'farm' and 'asset_1_id' in contract.metadata:  # TODO: refactor metadata to have different classes
                total_tokens = total_microtokens / (10 ** 6)  # TODO: fix not all lp tokens have 6 decimals
                lp_price = get_lp_price(contract.metadata['asset_1_id'], contract.metadata['asset_2_id'])
                res += total_tokens * lp_price
            else:
                if type == 'farm':  # TODO: ну это technical debt, рефачить метадату срочно promptly
                    asset_id_field_name = 'stakeToken'
                else:
                    asset_id_field_name = 'token'
                asset_id = int(cache['initial'][asset_id_field_name]['hex'], 16)
                asset_info = get_asset(asset_id)
                total_tokens = total_microtokens / (10 ** asset_info['params']['decimals'])
                asset_price = get_asset_price(asset_id)
                res += total_tokens * asset_price
        except Exception:
            print(traceback.print_exc(), '\n')
    return res


@cached(cache=TTLCache(maxsize=1, ttl=settings.total_tvl_ttl))
def get_tvl() -> dict:
    snapshot = get_last_snapshot()
    return {
        'farm': snapshot.farm_tvl,
        'distribution': snapshot.distribution_tvl,
        'total': snapshot.farm_tvl + snapshot.distribution_tvl
    }
