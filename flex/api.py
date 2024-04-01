import logging

from fastapi import APIRouter, HTTPException

from flex import db
from flex.contracts import all_contracts_to_pools
from flex.db.model import PoolTransaction, PoolStateInfo, PoolInfo, PoolType, UserState, UserStateInfo
from flex.pool_state import update_pool_state, update_all_pool_states, update_user_state
from flex.pools import pool_fetch_new_transactions_by_id

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/pool/transactions', tags=['Pools 2.0'])
async def get_pool_transactions(pool_id: int) -> list[PoolTransaction]:
    return await pool_fetch_new_transactions_by_id(pool_id)


@router.get('/pool/state', tags=['Pools 2.0'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    updated_state = await update_pool_state(pool_id)
    return updated_state.to_info()


@router.get('/pools/state/', tags=['Pools 2.0'])
async def get_pool_state() -> list[PoolStateInfo]:
    updated_states = await update_all_pool_states()
    return [state.to_info() for state in updated_states]


@router.get('/pools/info', tags=['Pools 2.0'])
async def get_pools_by(type: PoolType = PoolType.ANY) -> list[PoolInfo]:
    if type == PoolType.FARMING:
        return [pool.to_info() for pool in db.farming_pools.get_all()]
    elif type == PoolType.STAKING:
        return [pool.to_info() for pool in db.staking_pools.get_all()]
    else:
        return [pool.to_info() for pool in db.staking_pools.get_all()] + [pool.to_info() for pool in db.farming_pools.get_all()]


@router.post('/pools/user', tags=['Pools 2.0'])
async def get_user_pool_states_by_address(address: str) -> UserStateInfo:
    user_state = await update_user_state(address)
    if user_state is None:
        raise HTTPException(404, f'User with address {address} is not found!')
    return user_state.to_info()


@router.post('/pools/migrate', tags=['Pools 2.0'])
async def migrate_pools_from_contracts() -> dict:
    staking_pools, farming_pools = await all_contracts_to_pools()
    return {
        'staking_pools': staking_pools,
        'farming_pools': farming_pools,
    }
