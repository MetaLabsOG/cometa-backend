import asyncio
import logging
from datetime import datetime

from aiocache import cached
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_password
from flex import db
from flex.data.asset_prices import get_asset_price, get_all_asset_prices, get_asset_prices_by_query, create_asset_prices_batch
from flex.data.assets import get_all_asset_details, get_asset_details, get_asset_details_by_query, get_full_asset
from flex.db.model.blockchain import AssetDetails
from flex.db.model.liquidity_pools import LpStateInfo
from flex.db.model.priced import AssetPriceInfo
from flex.data.lp_states import get_lp_state_by_lp_token_id, update_lp_state
from flex.providers.vestige import get_algo_price_usd
from core.db.contracts import get_contracts_by_type, get_active_contracts

router = APIRouter()
logger = logging.getLogger(__name__)


# LP API

@router.post('/lp/states/update', tags=['LP'], dependencies=[Depends(require_password)])
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


@cached(ttl=60)
async def get_lp_state_info_by_lp_token_id(lp_token_id: int) -> LpStateInfo:
    lp_state = await get_lp_state_by_lp_token_id(lp_token_id)
    algo_price_usd = await get_algo_price_usd()
    return lp_state.to_info(algo_price_usd)


class LpStatePricedRequest(BaseModel):
    lp_token_id: int | None = None
    lp_token_ids: list[int] | None = None


@router.post('/lp/state/priced', tags=['LP'])
async def handle_get_lp_state_priced(body: LpStatePricedRequest):
    # Batch mode: return dict of results
    if body.lp_token_ids is not None:
        results = {}
        tasks = {
            token_id: get_lp_state_info_by_lp_token_id(token_id)
            for token_id in body.lp_token_ids
        }
        settled = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for token_id, result in zip(tasks.keys(), settled):
            if isinstance(result, BaseException):
                logger.warning(f'LP state fetch failed for {token_id}: {result}')
                results[str(token_id)] = None
            else:
                results[str(token_id)] = result
        return {"results": results}

    # Single mode: backward compatible
    if body.lp_token_id is not None:
        return await get_lp_state_info_by_lp_token_id(body.lp_token_id)

    raise HTTPException(status_code=400, detail="Provide lp_token_id or lp_token_ids")


# ASSETS API

@router.post('/asset', tags=['Assets'])
async def handle_get_asset_by_id(asset_id: int) -> AssetDetails:
    return await get_asset_details(asset_id)


@router.post('/asset/price', tags=['Assets'])
async def handle_get_asset_price_by_id(asset_id: int) -> AssetPriceInfo:
    try:
        asset_price = await get_asset_price(asset_id)
        return asset_price.to_info(datetime.now())
    except Exception as e:
        logger.error(f"Error getting price for asset {asset_id}: {e}")
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
@cached(ttl=60, namespace='farm_enriched', key_builder=lambda f, *args, **kwargs: f'farm_enriched:active={kwargs.get("active_only", args[0] if args else True)}')
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

        cache = m.get('cache')
        if cache:
            initial = cache.get('initial', {})
            for key in ('stakeToken', 'rewardToken', 'token'):
                val = _parse_bignum_safe(initial.get(key))
                if val is not None:
                    asset_ids.add(val)

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

        async def _fetch_asset_safe(aid):
            try:
                return await get_full_asset(aid)
            except Exception as e:
                logger.warning(f'Failed to fetch asset {aid}: {e}')
                return None

        fetched = await asyncio.gather(*[_fetch_asset_safe(aid) for aid in missing_asset_ids])
        assets_list.extend(a for a in fetched if a is not None)

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
