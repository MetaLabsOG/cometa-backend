import logging
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from env import settings
from flex import db
from flex.data.contracts import all_contracts_to_pools
from flex.data.costs import calculate_pool_state_cost
from flex.db.model import PoolStateInfo, PoolInfo, PoolType, UserStateInfo, PoolStateCost
from flex.data.pool_state import update_pool_state, update_all_pool_states, update_user_state

router = APIRouter()
logger = logging.getLogger(__name__)


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


@router.post('/pools/user/info', tags=['Pools 2.0'])
async def get_user_pool_states_by_address(address: str) -> UserStateInfo:
    user_state = await update_user_state(address)
    if user_state is None:
        raise HTTPException(404, f'User with address {address} is not found!')
    return user_state.to_info()


@router.get('/pool/cost', tags=['Pools 2.0'])
async def get_pool_state_cost_by_id(pool_id: int) -> PoolStateCost:
    pool_state = await update_pool_state(pool_id)
    return calculate_pool_state_cost(pool_state)


@router.post('/pools/migrate', tags=['Pools 2.0'])
async def migrate_pools_from_contracts() -> dict:
    staking_pools, farming_pools = await all_contracts_to_pools()
    return {
        'staking_pools': staking_pools,
        'farming_pools': farming_pools,
    }


# DB API

def check_password(password: str) -> None:
    if not secrets.compare_digest(settings.api_password, password):
        raise HTTPException(status_code=401, detail='Invalid password')


class DbGetParams(BaseModel):
    collection_name: str
    query: dict = {}
    show_last_cnt: int | None = None
    reverse: bool = False


@router.post('/db/find', tags=['DB'])
async def get_entities_by_dict_query(
        password: str,
        params: DbGetParams
) -> list[dict]:
    check_password(password)
    collection = db.get_collection_by_name(params.collection_name)
    if collection is None:
        raise HTTPException(status_code=404, detail=f'No such collection: {params.collection_name}!')
    entities = collection.get_many(**params.query)
    entity_dicts = [e.to_dict() for e in entities]
    if params.reverse:
        entity_dicts.reverse()
    if params.show_last_cnt is not None and len(entity_dicts) > params.show_last_cnt:
        entity_dicts = entity_dicts[-params.show_last_cnt:]
    return entity_dicts
