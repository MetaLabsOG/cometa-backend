import logging
from datetime import datetime
from enum import Enum

from aiocache import cached
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_password
from env import settings
from flex import db
from flex.blockchain.base import indexer_client, algod_client
from flex.blockchain.info import ALGO_ASSET
from flex.data.asset_prices import get_asset_price, get_all_asset_prices, get_asset_prices_by_query, create_asset_prices_batch
from flex.data.assets import get_all_asset_details, get_asset_details, get_asset_details_by_query, get_full_asset
from flex.data.stats import calculate_total_tvl_usd
from flex.db.model.liquidity_pools import LpStateInfo
from flex.migrations.contracts import all_contracts_to_pools
from flex.data.pool_state_priced import calculate_pool_state_cost, calculate_user_pool_state_cost
from flex.data.lp_states import get_lp_state_by_lp_token_id, recalculate_lp_state_price_algo_with_micros, \
    update_lp_state
from flex.data.lp_tokens import get_lp_token_by_id, get_all_lp_tokens
from flex.data.pools import get_pool_info_by_id, get_pools_by_query
from flex.db.model.blockchain import AssetDetails, LpTokenInfo
from flex.db.model.pool_states import UserStateInfo, PoolStateInfo
from flex.db.model.pools import PoolType, PoolInfo
from flex.db.model.priced import UserCost, PoolStateCost, AssetPriceInfo
from flex.providers.vestige import DexProvider, get_algo_price_usd
from flex.sync_pools import get_sync_pool_state_by_id, get_sync_user_state_by_address
from flex.tdr_stats import fetch_and_record_user_txns, fetch_and_record_pool_fees
from core.db.contracts import get_contracts_by_type, get_active_contracts
from core.util import parse_bignum

router = APIRouter()
logger = logging.getLogger(__name__)


# POOLS API

@router.get('/pool/', tags=['Pools 2.0'])
async def get_pool_by_id(pool_id: int) -> PoolInfo:
    return await get_pool_info_by_id(pool_id)


@router.delete('/pool/', tags=['Pools 2.0'])
async def remove_pool_by_id(pool_id: int) -> PoolInfo:
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
    now = datetime.now()
    return [state.to_info(now) for state in updated_states]


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
    if user_state is None:
        return UserStateInfo(address=address)
    return user_state.to_info()


@router.post('/pools/user/cost', tags=['Pools 2.0'])
async def get_user_pool_states_cost_by_address(address: str) -> UserCost:
    user_state = await get_sync_user_state_by_address(address)
    return await calculate_user_pool_state_cost(user_state)


@router.post('/pools/migrate', tags=['Pools 2.0'], dependencies=[Depends(require_password)])
async def migrate_pools_from_contracts() -> dict:
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


@router.post('/lp/state/recalculate', tags=['LP'])
async def handle_recalculate_lp_state_by_lp_token_id(lp_token_id: int) -> dict:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()

    recalculated_lp_state = await recalculate_lp_state_price_algo_with_micros(lp_state)
    updated_lp_state = await update_lp_state(lp_state)
    return {
        'initial': lp_state.to_info(algo_price_usd),
        'recalculated': recalculated_lp_state.to_info(algo_price_usd),
        'updated': updated_lp_state.to_info(algo_price_usd)
    }


@router.post('/lp/states/update', tags=['LP'])
async def handle_update_all_lp_states() -> list:
    all_lp_states = db.lp_states.get_all()
    logger.info(f'Updating {len(all_lp_states)} LP states')

    price_diffs = []
    for i, lp_state in enumerate(all_lp_states):
        logger.info(f'Updating LP state {i + 1}/{len(all_lp_states)}: id = {lp_state.token_id}')
        lp_state = await get_lp_state_by_lp_token_id(lp_state.token_id)
        updated_lp_state = await update_lp_state(lp_state)
        db.lp_states.update(updated_lp_state)
        if lp_state.token_price_algo != updated_lp_state.token_price_algo:
            price_diffs.append({
                'lp_token_id': lp_state.token_id,
                'initial': lp_state.token_price_algo,
                'updated': updated_lp_state.token_price_algo,
                'ratio': updated_lp_state.token_price_algo / lp_state.token_price_algo if lp_state.token_price_algo != 0 else 0
            })

    return price_diffs


@cached(ttl=30)
async def get_lp_state_info_by_lp_token_id(lp_token_id: int) -> LpStateInfo:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()
    return lp_state.to_info(algo_price_usd)


@router.post('/lp/state/priced', tags=['LP', 'Deprecated'])
async def handle_get_lp_state_by_lp_token_id_DEPRECATED(lp_token_id: int) -> LpStateInfo:
    return await get_lp_state_info_by_lp_token_id(lp_token_id)


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


def fetch_all_balances(asset_id, decimals):
    limit = 9000
    next_page = None
    holdings = []
    while True:
        response = indexer_client.asset_balances(asset_id=asset_id, limit=limit, next_page=next_page)
        holdings += [(r['address'], r['amount'] // decimals) for r in response['balances']]
        next_page = response.get('next-token')
        if next_page is None:
            break
    return holdings


@router.get('/asset/holdings', tags=['Assets'])
async def handle_get_asset_holdings_by_id(asset_id: int) -> dict:
    asset_info = algod_client.asset_info(asset_id) if asset_id != 0 else ALGO_ASSET  # TODO: refactor (now try to use original code)
    decimals = 10 ** asset_info['params']['decimals']
    holdings = fetch_all_balances(asset_id, decimals)
    sorted_holdings = sorted(holdings, key=lambda x: x[1], reverse=True)
    return {
        "name": "root",
        "children": [{"name": addr, "value": amt} for addr, amt in sorted_holdings[1:1000]],
        "totalHolders": len(holdings),
        "tokenName": asset_info['params']['name'],
        "tokenUnitName": asset_info['params']['unit-name']
    }


@router.post('/asset/price', tags=['Assets'])
async def handle_get_asset_price_by_id(asset_id: int) -> AssetPriceInfo:
    try:
        # Try to get the asset price (will create if not exists, refresh if old)
        asset_price = await get_asset_price(asset_id)
        return asset_price.to_info(datetime.now())
    except Exception as e:
        logger.error(f"Error getting price for asset {asset_id}: {e}")
        # Return 404 if asset not found, or 500 for other errors
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
        raise HTTPException(status_code=500, detail=f"Failed to get price for asset {asset_id}")


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


@router.post('/db/find', tags=['DB'], dependencies=[Depends(require_password)])
async def get_entities_by_dict_query(
        params: DbGetParams
) -> list[dict]:
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


@router.post('/db/count', tags=['DB'], dependencies=[Depends(require_password)])
async def get_entity_count(
        params: DbCountParams
) -> dict:
    collection = db.get_collection_by_name(params.collection_name)
    if collection is None:
        raise HTTPException(status_code=404, detail=f'No such collection: {params.collection_name}!')

    return {
        'count': collection.count(**params.query)
    }


# ENRICHED FARM ENDPOINT

def _parse_bignum_safe(obj) -> int | None:
    if obj is None:
        return None
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict) and obj.get('type') == 'BigNumber' and 'hex' in obj:
        return int(obj['hex'], 16)
    return None


def serialize_contract_slim(contract) -> dict:
    meta = dict(contract.metadata) if contract.metadata else {}
    cache = meta.pop('cache', None)
    if cache:
        initial = cache.get('initial', {})
        global_state = cache.get('global', {})
        meta['begin_block'] = meta.get('begin_block') or _parse_bignum_safe(initial.get('beginBlock'))
        meta['end_block'] = meta.get('end_block') or _parse_bignum_safe(initial.get('endBlock'))
        meta['lock_length_blocks'] = meta.get('lock_length_blocks') or _parse_bignum_safe(initial.get('lockLengthBlocks'))
        meta['total_staked'] = _parse_bignum_safe(global_state.get('totalStaked'))
        meta['reward_per_token'] = _parse_bignum_safe(global_state.get('rewardPerTokenStored'))
        meta['total_reward_amount'] = _parse_bignum_safe(initial.get('totalRewardAmount'))
        meta['total_algo_reward_amount'] = _parse_bignum_safe(initial.get('totalAlgoRewardAmount'))
        meta['stake_token'] = _parse_bignum_safe(initial.get('stakeToken')) or _parse_bignum_safe(initial.get('token'))
        meta['reward_token'] = _parse_bignum_safe(initial.get('rewardToken')) or _parse_bignum_safe(initial.get('token'))
        meta['last_update_block'] = _parse_bignum_safe(global_state.get('lastUpdateBlock'))
    return {
        'type': contract.type,
        'id': contract.id,
        'version': contract.version,
        'deployed_timestamp': contract.deployed_timestamp,
        'description': contract.description,
        'metadata': meta,
        'begin_date': contract.begin_date.isoformat() if contract.begin_date else None,
        'end_date': contract.end_date.isoformat() if contract.end_date else None,
    }


@router.get('/contracts/farm/enriched', tags=['Contracts'])
@cached(ttl=30, namespace='farm_enriched', key_builder=lambda f, *args, **kwargs: f'farm_enriched:active={kwargs.get("active_only", args[0] if args else True)}')
async def get_farm_enriched(active_only: bool = True):
    if active_only:
        farm_contracts = get_active_contracts('farm')
        distribution_contracts = get_active_contracts('distribution')
    else:
        farm_contracts = get_contracts_by_type('farm')
        distribution_contracts = get_contracts_by_type('distribution')
    contracts = farm_contracts + distribution_contracts

    # Collect asset IDs and LP token IDs from ALL pool contracts (farm + distribution)
    # so that user's ended pools also have pre-populated data
    all_contracts = get_contracts_by_type(None)

    asset_ids = set()
    lp_token_ids = set()
    for c in all_contracts:
        m = c.metadata or {}
        for key in ('stake_token_id', 'reward_token_id', 'asset1_id', 'asset2_id'):
            val = m.get(key)
            if val is not None:
                asset_ids.add(int(val))

        # Also extract from cache if present
        cache = m.get('cache')
        if cache:
            initial = cache.get('initial', {})
            for key in ('stakeToken', 'rewardToken', 'token'):
                val = _parse_bignum_safe(initial.get(key))
                if val is not None:
                    asset_ids.add(val)

        # Collect LP token IDs from DEX contracts
        if m.get('dex'):
            if cache:
                stake_token = _parse_bignum_safe(cache.get('initial', {}).get('stakeToken'))
                if stake_token:
                    lp_token_ids.add(stake_token)
            stake_token_meta = m.get('stake_token_id')
            if stake_token_meta:
                lp_token_ids.add(int(stake_token_meta))

    asset_ids.discard(0)  # ALGO doesn't need lookup

    # Batch-fetch assets from DB, auto-populate missing ones from algod
    current_time = datetime.now()
    assets_list = db.assets.get_many_by_query({'id': {'$in': list(asset_ids)}}) if asset_ids else []
    existing_asset_ids = {a.id for a in assets_list}
    missing_asset_ids = asset_ids - existing_asset_ids
    if missing_asset_ids:
        logger.info(f'Auto-populating {len(missing_asset_ids)} missing assets from algod')
        for aid in missing_asset_ids:
            try:
                asset = await get_full_asset(aid)
                assets_list.append(asset)
            except Exception as e:
                logger.warning(f'Failed to fetch asset {aid}: {e}')

    # Batch-fetch prices from DB, auto-populate missing ones via batch Vestige API
    all_price_ids = asset_ids | {0}
    prices_list = db.asset_prices.get_many_by_query({'id': {'$in': list(all_price_ids)}})
    existing_price_ids = {p.id for p in prices_list}
    missing_price_ids = all_price_ids - existing_price_ids
    if missing_price_ids:
        logger.info(f'Auto-populating {len(missing_price_ids)} missing prices (batch)')
        from flex.blockchain.info import get_current_round
        try:
            current_round = await get_current_round()
            new_prices = await create_asset_prices_batch(
                list(missing_price_ids), current_round
            )
            prices_list.extend(new_prices)
            logger.info(f'Batch created {len(new_prices)}/{len(missing_price_ids)} prices')
        except Exception as e:
            logger.error(f'Batch price creation failed: {e}')

    # Batch-fetch ALL LP states (isolated error handling — don't break assets/prices if LP fetch fails)
    # Fetching all (~200) instead of filtering by $in because some token_ids are stored
    # as BSON Long in MongoDB and don't match Python int queries
    lp_states_dict = {}
    try:
        algo_price_usd = await get_algo_price_usd()
        lp_states_list = db.lp_states.get_all()
        lp_states_dict = {s.token_id: s.to_info(algo_price_usd, current_time).to_dict() for s in lp_states_list}
        logger.info(f'Enriched: returning {len(lp_states_dict)} LP states (from {len(lp_states_list)} in DB)')
    except Exception as e:
        logger.error(f'Failed to fetch LP states for enriched endpoint: {e}')

    assets_dict = {a.id: a.to_details().to_dict() for a in assets_list}
    prices_dict = {p.id: p.to_info(current_time).to_dict() for p in prices_list}

    return {
        'contracts': [serialize_contract_slim(c) for c in contracts],
        'assets': assets_dict,
        'prices': prices_dict,
        'lp_states': lp_states_dict,
    }
