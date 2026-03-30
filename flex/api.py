import asyncio
import logging
from datetime import datetime

from aiocache import cached
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from flex import db
from flex.data.asset_prices import get_asset_price, get_all_asset_prices, get_asset_prices_by_query, create_asset_prices_batch
from flex.data.assets import get_all_asset_details, get_asset_details, get_asset_details_by_query, get_full_asset
from flex.db.model.blockchain import AssetDetails
from flex.db.model.priced import AssetPriceInfo
from core.db.contracts import get_contracts_by_type, get_active_contracts

router = APIRouter()
logger = logging.getLogger(__name__)


# LP API


class LpStatePricedRequest(BaseModel):
    lp_token_id: int | None = None
    lp_token_ids: list[int] | None = None


@router.post('/lp/state/priced', tags=['LP'])
async def handle_get_lp_state_priced(body: LpStatePricedRequest):
    """Return LP token prices from asset_prices collection."""
    token_ids = body.lp_token_ids or ([body.lp_token_id] if body.lp_token_id else None)
    if not token_ids:
        raise HTTPException(status_code=400, detail="Provide lp_token_id or lp_token_ids")

    results = {}
    for tid in token_ids:
        price = db.asset_prices.get_one(id=tid)
        results[str(tid)] = {'token_id': tid, 'token_price_algo': price.price_algo, 'token_price_usd': price.price_usd} if price else None

    if body.lp_token_ids is not None:
        return {"results": results}
    # Single mode: backward compatible
    return results.get(str(body.lp_token_id))


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

    # LP prices are now in asset_prices collection (populated by background worker).
    # Keep lp_states key as empty dict for frontend compatibility.
    lp_states_dict = {}

    assets_dict = {a.id: a.to_details().to_dict() for a in assets_list}
    prices_dict = {p.id: p.to_info(current_time).to_dict() for p in prices_list}

    return {
        'contracts': [serialize_contract_slim(c) for c in contracts],
        'assets': assets_dict,
        'prices': prices_dict,
        'lp_states': lp_states_dict,
    }
