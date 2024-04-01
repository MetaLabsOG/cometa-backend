from fastapi import APIRouter

from flex import db
from flex.contracts import all_contracts_to_pools
from flex.db.model import PoolTransaction, PoolStateInfo, PoolInfo, PoolType
from flex.pool_state import record_new_pool_transactions, update_all_pool_states
from flex.pools import pool_fetch_new_transactions_by_id

router = APIRouter()


@router.get('/pool/transactions', tags=['Pools 2.0'])
async def get_pool_transactions(pool_id: int) -> list[PoolTransaction]:
    return pool_fetch_new_transactions_by_id(pool_id)


@router.get('/pool/state', tags=['Pools 2.0'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    return record_new_pool_transactions(pool_id).to_info()


@router.get('/pools/state/', tags=['Pools 2.0'])
async def get_pool_state() -> list[PoolStateInfo]:
    updated_states = update_all_pool_states()
    return [state.to_info() for state in updated_states]


@router.get('/pools/info', tags=['Pools 2.0'])
async def get_pools_by(type: PoolType = PoolType.ANY) -> list[PoolInfo]:
    if type == PoolType.FARMING:
        return [pool.to_info() for pool in db.farming_pools.get_all()]
    elif type == PoolType.STAKING:
        return [pool.to_info() for pool in db.staking_pools.get_all()]
    else:
        return [pool.to_info() for pool in db.staking_pools.get_all()] + [pool.to_info() for pool in db.farming_pools.get_all()]


@router.post('/pools/migrate', tags=['New Pools'])
async def migrate_pools_from_contracts() -> dict:
    staking_pools, farming_pools = await all_contracts_to_pools()
    return {
        'staking_pools': len(staking_pools),
        'farming_pools': len(farming_pools),
    }
