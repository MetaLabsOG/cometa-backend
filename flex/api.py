from fastapi import APIRouter

from flex.db.model import PoolTransaction, PoolStateInfo
from flex.pool_state import record_new_pool_transactions, update_all_pool_states
from flex.pools import pool_fetch_new_transactions_by_id

router = APIRouter()


@router.get('/pool/transactions', tags=['Pool State'])
async def get_pool_transactions(pool_id: int) -> list[PoolTransaction]:
    return pool_fetch_new_transactions_by_id(pool_id)


@router.get('/pool/state', tags=['Pool State'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    return record_new_pool_transactions(pool_id).to_info()


@router.get('/pool/all', tags=['Pool State'])
async def get_pool_state() -> list[PoolStateInfo]:
    updated_states = update_all_pool_states()
    return [state.to_info() for state in updated_states]
