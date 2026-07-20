import logging
import time
from dataclasses import dataclass
from typing import Optional

from cachetools import FIFOCache, TTLCache, cached
from dataclasses_json import dataclass_json

from core.db.mongodb import get_db_collection
from core.tinychart import get_asset_price
from dexes.tinyman import get_pool_info, init_tinyman_client
from env import settings


@dataclass_json
@dataclass
class CometaSnapshot:
    timestamp: float
    farm_tvl: float = 0
    staking_tvl: float = 0
    distribution_tvl: float | None = None


tiny_client = init_tinyman_client()
snapshots = get_db_collection(settings.db_name, "snapshot")

logger = logging.getLogger(__name__)


def save_snapshot(farm_tvl: float, distribution_tvl: float, staking_tvl: float) -> CometaSnapshot:
    cur_time = time.time()
    snapshot = CometaSnapshot(
        farm_tvl=farm_tvl, distribution_tvl=distribution_tvl, timestamp=cur_time, staking_tvl=staking_tvl
    )
    snapshots.insert_one(snapshot.to_dict())
    return snapshot


def get_last_snapshot() -> Optional[CometaSnapshot]:
    res = snapshots.find_one(sort=[("$natural", -1)])
    return CometaSnapshot.from_dict(res) if res else None


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
    if snapshot is None:
        return {"farm": 0, "distribution": 0, "staking": 0, "total": 0}
    farm = snapshot.farm_tvl or 0
    distribution = snapshot.distribution_tvl or 0
    staking = snapshot.staking_tvl or 0
    return {"farm": farm, "distribution": distribution, "staking": staking, "total": farm + distribution + staking}
