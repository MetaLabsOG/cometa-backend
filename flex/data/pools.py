import logging

from cachetools import cached, LRUCache

from flex import db
from flex.db.model.pools import PoolInfo, StakingPool, FarmingPool

logger = logging.getLogger(__name__)


CometaPool = StakingPool | FarmingPool


# TODO: refactor not to suck dicks between two collections
@cached(cache=LRUCache(maxsize=1024))  # pool info is almost never updated
def get_pool_info_by_id(pool_id: int) -> PoolInfo:
    pool = db.staking_pools.get_by_primary_key(pool_id, throw_ex=False)
    if pool is not None:
        return pool.to_info()

    pool = db.farming_pools.get_by_primary_key(pool_id, throw_ex=False)
    if pool is not None:
        return pool.to_info()

    raise ValueError(f'Pool {pool_id} not found')
