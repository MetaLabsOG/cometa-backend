import logging

from aiocache import cached

from flex import db
from flex.db.model.pools import PoolInfo
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
