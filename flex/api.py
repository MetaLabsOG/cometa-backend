from fastapi import APIRouter

from flex import db
from flex.contracts import all_contracts_to_pools
from flex.db.model import PoolTransaction, PoolStateInfo, FarmingPool, StakingPool
from flex.pool_state import record_new_pool_transactions, update_all_pool_states
from flex.pools import pool_fetch_new_transactions_by_id

router = APIRouter()


@router.get('/pool/transactions', tags=['Pool State'])
async def get_pool_transactions(pool_id: int) -> list[PoolTransaction]:
    return pool_fetch_new_transactions_by_id(pool_id)


@router.get('/pool/state', tags=['Pool State'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    return record_new_pool_transactions(pool_id).to_info()


@router.get('/pool/state/all', tags=['Pool State'])
async def get_pool_state() -> list[PoolStateInfo]:
    updated_states = update_all_pool_states()
    return [state.to_info() for state in updated_states]


@router.get('/pools/farming', tags=['New Pools'])
async def get_farming_pools_by() -> list[FarmingPool]:
    return db.farming_pools.get_all()


@router.get('/pools/staking', tags=['New Pools'])
async def get_staking_pools_by() -> list[StakingPool]:
    return db.staking_pools.get_all()


@router.post('/pools/migrate', tags=['New Pools'])
async def migrate_pools_from_contracts() -> dict:
    staking_pools, farming_pools = all_contracts_to_pools()
    return {
        'staking_pools': len(staking_pools),
        'farming_pools': len(farming_pools),
    }
