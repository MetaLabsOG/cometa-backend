import logging
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from env import settings
from flex import db
from flex.data.assets import get_asset
from flex.migrations.contracts import all_contracts_to_pools
from flex.data.costs import calculate_pool_state_cost, calculate_user_pool_state_cost
from flex.data.lp_states import fetch_priced_lp_state_by_token, PricedLpState, get_lp_state_by_lp_token_id
from flex.data.lp_tokens import get_lp_token_by_id
from flex.data.pools import get_pool_info_by_id
from flex.db.model.blockchain import LpToken, Asset
from flex.db.model.liquidity_pools import LpStateInfo
from flex.db.model.pool_states import UserStateInfo, PoolStateInfo
from flex.db.model.pools import PoolType, PoolInfo
from flex.db.model.priced import UserCost, PoolStateCost
from flex.sync_pools import get_sync_pool_state_by_id, get_sync_user_state_by_address

router = APIRouter()
logger = logging.getLogger(__name__)


def check_password(password: str) -> None:
    if not secrets.compare_digest(settings.api_password, password):
        raise HTTPException(status_code=401, detail='Invalid password')


# POOLS API

@router.get('/pool/', tags=['Pools 2.0'])
async def get_pool_by_id(pool_id: int) -> PoolInfo:
    return get_pool_info_by_id(pool_id)


@router.get('/pool/state', tags=['Pools 2.0'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    updated_state = await get_sync_pool_state_by_id(pool_id)
    return updated_state.to_info()


@router.get('/pool/cost', tags=['Pools 2.0'])
async def get_pool_state_cost_by_id(pool_id: int) -> PoolStateCost:
    pool_state = await get_sync_pool_state_by_id(pool_id)
    return calculate_pool_state_cost(pool_state)


@router.get('/pools/', tags=['Pools 2.0'])
async def get_pools_by(type: PoolType = PoolType.ANY) -> list[PoolInfo]:
    if type == PoolType.FARMING:
        return [pool.to_info() for pool in db.farming_pools.get_all()]
    elif type == PoolType.STAKING:
        return [pool.to_info() for pool in db.staking_pools.get_all()]
    else:
        return [pool.to_info() for pool in db.staking_pools.get_all()] + [pool.to_info() for pool in db.farming_pools.get_all()]


@router.post('/pools/state/', tags=['Pools 2.0'])
async def get_pool_state(
        max_count: int | None = None
) -> list[PoolStateInfo]:
    pool_states = db.pool_states.get_all()
    if max_count is not None:
        pool_states = pool_states[:max_count]
    updated_states = []
    for pool_state in pool_states:
        # TODO: improve
        updated_state = await get_sync_pool_state_by_id(pool_state.pool_id)
        updated_states.append(updated_state)
    return [state.to_info() for state in updated_states]


@router.post('/pools/cost', tags=['Pools 2.0'])
async def get_pool_states_cost() -> list[PoolStateCost]:
    previous_states = db.pool_states.get_all()
    updated_states = []
    for state in previous_states:
        updated_state = await get_sync_pool_state_by_id(state.pool_id)
        updated_states.append(updated_state)
    return [calculate_pool_state_cost(s) for s in updated_states]


@router.post('/pools/user/state', tags=['Pools 2.0'])
async def get_user_pool_states_by_address(address: str) -> UserStateInfo:
    user_state = await get_sync_user_state_by_address(address)
    return user_state.to_info()


@router.post('/pools/user/cost', tags=['Pools 2.0'])
async def get_user_pool_states_cost_by_address(address: str) -> UserCost:
    user_state = await get_sync_user_state_by_address(address)
    return calculate_user_pool_state_cost(user_state)


@router.post('/pools/migrate', tags=['Pools 2.0'])
async def migrate_pools_from_contracts(password: str) -> dict:
    check_password(password)
    return await all_contracts_to_pools()


# LP API

@router.post('/lp/token', tags=['LP'])
async def get_lp_token_info(lp_token_id: int) -> LpToken:
    return get_lp_token_by_id(lp_token_id)


@router.post('/lp/state/priced', tags=['LP'])
async def get_priced_lp_state_by_token_id(lp_token_id: int) -> PricedLpState:
    lp_token = get_lp_token_by_id(lp_token_id)
    return fetch_priced_lp_state_by_token(lp_token)


@router.post('/lp/state/', tags=['LP'])
async def handle_get_lp_state_by_lp_token_id(lp_token_id: int) -> LpStateInfo:
    lp_state = get_lp_state_by_lp_token_id(lp_token_id)
    return lp_state.to_info()


@router.post('/lp/states', tags=['LP'])
async def get_all_lp_states() -> list[LpStateInfo]:
    lp_states = db.lp_states.get_all()
    return [state.to_info() for state in lp_states]


@router.post('/info/lp/state/', tags=['LP'])
async def handle_get_lp_state_by_lp_token_id_OLD(lp_token_id: int) -> LpStateInfo:
    lp_state = get_lp_state_by_lp_token_id(lp_token_id)
    return lp_state.to_info()


# ASSETS API

@router.post('/asset', tags=['Assets'])
async def get_asset_info_by_id(asset_id: int) -> Asset:
    return get_asset(asset_id)


# DB API

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


class DbCountParams(BaseModel):
    collection_name: str
    query: dict = {}


@router.post('/db/count', tags=['DB'])
async def get_entity_count(
        password: str,
        params: DbCountParams
) -> dict:
    check_password(password)
    collection = db.get_collection_by_name(params.collection_name)
    if collection is None:
        raise HTTPException(status_code=404, detail=f'No such collection: {params.collection_name}!')

    return {
        'count': collection.count(**params.query)
    }
