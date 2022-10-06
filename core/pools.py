from typing import Optional, List

from core import mongodb
from core.model import PoolInfo

pool_db = mongodb.database.pools


def add_pool(pool: PoolInfo) -> PoolInfo:
    pool_db.insert_one(pool.to_dict())
    return pool


def update_pool(pool: PoolInfo) -> PoolInfo:
    pool_db.update_one({'id': pool.id}, {'$set': {
        'current_apr': pool.current_apr,
        'status': pool.status}}
    )
    return pool


def get_pool(args: dict) -> Optional[PoolInfo]:
    pool = pool_db.find_one(args)
    return PoolInfo.from_dict(pool) if pool is not None else None


def get_pools(args: dict) -> List[PoolInfo]:
    pools = pool_db.find(args)
    return [PoolInfo.from_dict(p) for p in pools]
