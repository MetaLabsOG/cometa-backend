import logging

from aiocache import cached

from flex import db
from flex.db.model.pools import PoolInfo, PoolType
from flex.util import build_key_str

logger = logging.getLogger(__name__)


# TODO: refactor not to suck dicks between two collections
@cached(namespace='pool_info_by_id', key_builder=build_key_str)  # pool info is almost never updated
async def get_pool_info_by_id(pool_id: int) -> PoolInfo:
    pool = db.staking_pools.get_by_primary_key(pool_id, throw_ex=False)
    if pool is not None:
        return pool.to_info()

    pool = db.farming_pools.get_by_primary_key(pool_id, throw_ex=False)
    if pool is not None:
        return pool.to_info()

    raise ValueError(f'Pool {pool_id} not found')


async def get_pools_by_query(query_dict: dict, pool_type: PoolType = PoolType.ANY) -> list[PoolInfo]:
    if pool_type == PoolType.FARMING:
        return [pool.to_info() for pool in db.farming_pools.get_many(**query_dict)]
    elif pool_type == PoolType.STAKING:
        return [pool.to_info() for pool in db.staking_pools.get_many(**query_dict)]
    else:
        return [pool.to_info() for pool in db.staking_pools.get_many(**query_dict)] + [pool.to_info() for pool in db.farming_pools.get_many(**query_dict)]


async def get_all_pools() -> list[PoolInfo]:
    return await get_pools_by_query({})
