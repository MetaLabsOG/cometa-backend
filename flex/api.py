import logging
import secrets
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from env import settings
from flex import db
from flex.data.asset_prices import get_asset_price, get_all_asset_prices, get_asset_prices_by_query
from flex.data.assets import get_all_asset_details, get_asset_details, get_asset_details_by_query
from flex.data.stats import calculate_total_tvl_usd
from flex.db.model.liquidity_pools import LpStateInfo
from flex.migrations.contracts import all_contracts_to_pools
from flex.data.pool_state_priced import calculate_pool_state_cost, calculate_user_pool_state_cost
from flex.data.lp_states import get_lp_state_by_lp_token_id
from flex.data.lp_tokens import get_lp_token_by_id, get_all_lp_tokens
from flex.data.pools import get_pool_info_by_id, get_pools_by_query
from flex.db.model.blockchain import AssetDetails, LpTokenInfo
from flex.db.model.pool_states import UserStateInfo, PoolStateInfo
from flex.db.model.pools import PoolType, PoolInfo
from flex.db.model.priced import UserCost, PoolStateCost, AssetPriceInfo
from flex.providers.vestige import DexProvider, get_algo_price_usd
from flex.sync_pools import get_sync_pool_state_by_id, get_sync_user_state_by_address
from flex.tdr_stats import fetch_and_record_user_txns, fetch_and_record_pool_fees

router = APIRouter()
logger = logging.getLogger(__name__)


def check_password(password: str) -> None:
    if not secrets.compare_digest(settings.api_password, password):
        raise HTTPException(status_code=401, detail='Invalid password')


# POOLS API

@router.get('/pool/', tags=['Pools 2.0'])
async def get_pool_by_id(pool_id: int) -> PoolInfo:
    return await get_pool_info_by_id(pool_id)


@router.get('/pool/state', tags=['Pools 2.0'])
async def get_pool_state(pool_id: int) -> PoolStateInfo:
    updated_state = await get_sync_pool_state_by_id(pool_id)
    return updated_state.to_info()


@router.get('/pool/cost', tags=['Pools 2.0'])
async def get_pool_state_cost_by_id(pool_id: int) -> PoolStateCost:
    pool_state = await get_sync_pool_state_by_id(pool_id)
    return await calculate_pool_state_cost(pool_state)


@router.get('/pools/', tags=['Pools 2.0'])
async def get_pools_by(type: PoolType = PoolType.ANY, stake_token_id: int | None = None) -> list[PoolInfo]:
    query_dict = {}
    if stake_token_id is not None:
        query_dict['stake_token.id'] = stake_token_id
    return await get_pools_by_query(pool_type=type, query_dict=query_dict)


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
    return [(await calculate_pool_state_cost(s)) for s in updated_states]


@router.post('/pools/user/state', tags=['Pools 2.0'])
async def get_user_pool_states_by_address(address: str) -> UserStateInfo:
    user_state = await get_sync_user_state_by_address(address)
    return user_state.to_info()


@router.post('/pools/user/cost', tags=['Pools 2.0'])
async def get_user_pool_states_cost_by_address(address: str) -> UserCost:
    user_state = await get_sync_user_state_by_address(address)
    return await calculate_user_pool_state_cost(user_state)


@router.post('/pools/migrate', tags=['Pools 2.0'])
async def migrate_pools_from_contracts(password: str) -> dict:
    check_password(password)
    return await all_contracts_to_pools()


@router.post('/pools/tvl', tags=['Pools 2.0'])
async def handle_get_pools_tvl() -> dict:
    return await calculate_total_tvl_usd()


# LP API

@router.post('/lp/token', tags=['LP'])
async def get_lp_token_info(lp_token_id: int) -> LpTokenInfo:
    return (await get_lp_token_by_id(lp_token_id)).to_info()


@router.post('/lp/tokens', tags=['LP'])
async def get_lp_token_info(lp_token_ids: list[int] | None = None) -> list[LpTokenInfo]:
    return [token.to_info() for token in (await get_all_lp_tokens())]


@router.post('/lp/state/', tags=['LP'])
async def handle_get_lp_state_by_lp_token_id(lp_token_id: int) -> LpStateInfo:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()
    return lp_state.to_info(algo_price_usd)


@router.post('/lp/state/priced', tags=['LP', 'Deprecated'])
async def handle_get_lp_state_by_lp_token_id_DEPRECATED(lp_token_id: int) -> LpStateInfo:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()
    return lp_state.to_info(algo_price_usd)


@router.post('/lp/states', tags=['LP'])
async def get_lp_states_by(
        max_count: int | None = None,
        lp_token_id: int | None = None,
        dex_provider: DexProvider = DexProvider.ANY,
        asset_id: int | None = None
) -> list[LpStateInfo]:
    query_dict = {}
    if lp_token_id is not None:
        query_dict['token_id'] = lp_token_id
    if dex_provider != DexProvider.ANY:
        query_dict['dex_provider'] = dex_provider
    if asset_id is not None:
        query_dict['$or'] = [{'asset1_id': asset_id}, {'asset2_id': asset_id}]
    lp_states = db.lp_states.get_many_by_query(query_dict)

    if max_count is not None:
        lp_states = lp_states[:max_count]

    current_time = datetime.now()
    algo_price_usd = await get_algo_price_usd()

    return [state.to_info(algo_price_usd, current_time=current_time) for state in lp_states]


@router.post('/info/lp/state/', tags=['LP'])
async def handle_get_lp_state_by_lp_token_id_OLD(lp_token_id: int) -> LpStateInfo:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()
    return lp_state.to_info(algo_price_usd)


# ASSETS API

@router.post('/asset', tags=['Assets'])
async def handle_get_asset_by_id(asset_id: int) -> AssetDetails:
    return await get_asset_details(asset_id)


@router.post('/asset/price', tags=['Assets'])
async def handle_get_asset_price_by_id(asset_id: int) -> AssetPriceInfo:
    return (await get_asset_price(asset_id)).to_info(datetime.now())


class AssetsParams(BaseModel):
    ids: list[int] | None = None

    def to_query_dict(self) -> dict:
        query_dict = {}
        if self.ids:
            query_dict['id'] = {'$in': self.ids}
        return query_dict


@router.post('/assets', tags=['Assets'])
async def handle_get_assets_by(params: AssetsParams) -> list[AssetDetails]:
    query_dict = params.to_query_dict()
    if len(query_dict) == 0:
        return await get_all_asset_details()
    return await get_asset_details_by_query(query_dict)


@router.post('/assets/price', tags=['Assets'])
async def handle_get_assets_prices_by(params: AssetsParams) -> list[AssetPriceInfo]:
    query_dict = params.to_query_dict()
    current_time = datetime.now()
    if len(query_dict) == 0:
        return await get_all_asset_prices(current_time=current_time)
    else:
        return await get_asset_prices_by_query(query_dict, current_time=current_time)


# STATS

@router.post('/users/txns', tags=['Stats'])
async def handle_get_user_txns() -> int:
    user_txns = await fetch_and_record_user_txns()
    return len(user_txns)


@router.post('/pools/fees', tags=['Stats'])
async def handle_get_pool_fees() -> int:
    pool_fees = await fetch_and_record_pool_fees()
    return len(pool_fees)


# DB API

class DbGetParams(BaseModel):
    collection_name: str
    query: dict = {}
    limit: int | None = None
    reversed: bool = False
    sort_by: str | None = None


@router.post('/db/find', tags=['DB'])
async def get_entities_by_dict_query(
        password: str,
        params: DbGetParams
) -> list[dict]:
    check_password(password)
    collection = db.get_collection_by_name(params.collection_name)
    if collection is None:
        raise HTTPException(status_code=404, detail=f'No such collection: {params.collection_name}!')
    entities = collection.get_many_by_query(
        query_dict=params.query,
        sort_by=params.sort_by,
        reversed=params.reversed,
        limit=params.limit
    )
    return [e.to_dict() for e in entities]


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
