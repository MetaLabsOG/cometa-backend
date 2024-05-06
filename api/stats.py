import logging
import time
from dataclasses import dataclass
from typing import Optional

from cachetools import cached, TTLCache, FIFOCache
from dataclasses_json import dataclass_json

from core.db.mongodb import get_db_collection
from core.tinychart import get_asset_price
from dexes.tinyman import init_tinyman_client, get_pool_info
from env import settings


@dataclass_json
@dataclass
class CometaSnapshot:
    timestamp: float
    farm_tvl: float = 0
    staking_tvl: float = 0
    distribution_tvl: float | None = None


tiny_client = init_tinyman_client(settings.algod_address)
snapshots = get_db_collection(settings.db_name, 'snapshot')

logger = logging.getLogger(__name__)


def save_snapshot(farm_tvl: float, distribution_tvl: float, staking_tvl: float) -> CometaSnapshot:
    cur_time = time.time()
    snapshot = CometaSnapshot(
        farm_tvl=farm_tvl,
        distribution_tvl=distribution_tvl,
        timestamp=cur_time,
        staking_tvl=staking_tvl
    )
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
    if pool.total_lp_tokens == 0:
        return 0
    lp_price = total_cost / pool.total_lp_tokens
    return lp_price


@cached(cache=FIFOCache(maxsize=1024))
def get_asset_info(asset_id: int) -> dict:
    return tiny_client.fetch_asset(asset_id)


@cached(cache=TTLCache(maxsize=1, ttl=settings.total_tvl_ttl))
def get_tvl() -> dict:
    snapshot = get_last_snapshot()
    return {
        'farm': snapshot.farm_tvl,
        'distribution': snapshot.distribution_tvl,
        'staking': snapshot.staking_tvl,
        'total': snapshot.farm_tvl + snapshot.distribution_tvl + snapshot.staking_tvl
    }
