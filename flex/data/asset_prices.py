import logging
from datetime import datetime
import asyncio
from typing import List

from aiocache import cached

from env import settings
from flex import db
from flex.blockchain.info import get_current_round
from flex.data.assets import get_asset_details
from flex.db.model.priced import AssetPrice, AssetPriceInfo
from flex.providers.vestige import vestige_full_asset_price, get_algo_price_usd
from flex.meta_error import MetaError
from flex.util import build_key_str

logger = logging.getLogger(__name__)


def _upsert_asset_price(asset_price: AssetPrice):
    """Atomic insert-or-update asset price by id (prevents duplicates)."""
    asset_price.updated = datetime.now()
    doc = asset_price.to_dict()
    doc.pop('_id', None)
    created = doc.pop('created', asset_price.created)
    db.asset_prices.mongodb_collection.update_one(
        {'id': asset_price.id},
        {'$set': doc, '$setOnInsert': {'created': created}},
        upsert=True,
    )


async def create_asset_prices_batch(
    asset_ids: list[int],
    current_round: int,
    algo_price_usd: float | None = None,
) -> list[AssetPrice]:
    """Create prices for multiple assets using Vestige batch API.

    LP token prices are handled by the background worker (lp_prices.py),
    not by this function.
    """
    from flex.providers.vestige import vestige_batch_prices

    if not asset_ids:
        return []

    algo_price_usd = algo_price_usd or await get_algo_price_usd()

    # Batch fetch from Vestige
    vestige_prices = []
    batch_result = await vestige_batch_prices(asset_ids)
    for aid in asset_ids:
        price = batch_result.get(aid)
        if price is None or (price.algo <= 0 and price.usd <= 0):
            logger.warning(f'No valid Vestige price for asset {aid}')
            continue
        try:
            asset_details = await get_asset_details(aid)
            ap = AssetPrice(
                id=aid,
                name=asset_details.name,
                price_algo=price.algo,
                price_usd=price.usd,
                last_update_round=current_round,
            )
            _upsert_asset_price(ap)
            vestige_prices.append(ap)
        except Exception as e:
            logger.warning(f'Failed to store Vestige price for asset {aid}: {e}')

    logger.info(f'Batch prices: {len(vestige_prices)}/{len(asset_ids)} created')
    return vestige_prices


async def create_asset_price(asset_id: int, current_round: int, algo_price_usd: float | None = None) -> AssetPrice:
    try:
        asset_details = await get_asset_details(asset_id)
        logger.debug(f'Creating asset price {asset_id} = {asset_details.name}')

        algo_price_usd = algo_price_usd or await get_algo_price_usd()

        try:
            price = await vestige_full_asset_price(asset_id)
            if price.algo <= 0 and price.usd <= 0:
                logger.warning(f"Vestige returned zero/negative price for asset {asset_id} ({asset_details.name})")
                raise MetaError(f"Vestige returned invalid price for asset {asset_id}")
            asset_price = AssetPrice(
                id=asset_id,
                name=asset_details.name,
                price_algo=price.algo,
                price_usd=price.usd,
                last_update_round=current_round
            )
        except MetaError:
            raise
        except Exception as e:
            logger.error(f"Failed to get price from Vestige for asset {asset_id}: {e}")
            raise MetaError(f"Could not fetch price for asset {asset_id}")

        _upsert_asset_price(asset_price)
        logger.info(f'Asset Price {asset_price.name} (id={asset_price.id}): usd={asset_price.price_usd}, algo={asset_price.price_algo}')
        return asset_price
    except Exception as e:
        logger.error(f"Failed to create asset price for {asset_id}: {e}")
        raise



async def update_asset_price(asset_price: AssetPrice, current_round: int, algo_price_usd: float | None = None) -> AssetPrice:
    logger.debug(f'Updating Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')
    old_price_algo = asset_price.price_algo
    old_price_usd = asset_price.price_usd

    try:
        price = await vestige_full_asset_price(asset_id=asset_price.id)
        asset_price.price_algo = price.algo
        asset_price.price_usd = price.usd
    except Exception as e:
        logger.error(f"Failed to update price for asset {asset_price.id}: {e}")
        logger.info(f"Keeping old price values for asset {asset_price.id}")
        asset_price.price_algo = old_price_algo
        asset_price.price_usd = old_price_usd

    asset_price.last_update_round = current_round
    _upsert_asset_price(asset_price)

    logger.debug(f'Fresh Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')
    return asset_price


@cached(ttl=120, namespace='asset_price', key_builder=build_key_str)  # 120 seconds (2 minutes) TTL
async def get_asset_price(asset_id: int) -> AssetPrice:
    return await get_asset_price_not_cached(asset_id)


async def get_asset_price_not_cached(asset_id: int) -> AssetPrice:
    asset_price = db.asset_prices.get_one(id=asset_id)
    current_round = await get_current_round()
    
    # If asset doesn't exist in cache/database, create it
    if asset_price is None:
        try:
            asset_price = await create_asset_price(asset_id, current_round)
        except Exception as e:
            logger.error(f"Failed to create asset price for ID {asset_id}: {e}")
            raise
    # If asset exists but cache is old (>120s), try to refresh it
    elif current_round - asset_price.last_update_round > 120:  # 120 seconds TTL
        try:
            asset_price = await update_asset_price(asset_price, current_round)
        except Exception as e:
            logger.error(f"Failed to update asset price for ID {asset_id}, using cached value: {e}")
            # On failure, return the old cached value
    
    return asset_price


async def update_stale_asset_prices(asset_prices: List[AssetPrice]) -> List[AssetPrice]:
    """
    Efficiently update stale asset prices in batches.
    
    Args:
        asset_prices: List of asset prices to check and potentially update
        
    Returns:
        List of updated asset prices
    """
    if not asset_prices:
        return []
        
    current_round = await get_current_round()
    stale_prices = []
    
    # Find stale prices that need updating
    for price in asset_prices:
        if current_round - price.last_update_round > settings.asset_prices_ttl:
            stale_prices.append(price)
    
    if not stale_prices:
        return asset_prices
        
    logger.info(f"Updating {len(stale_prices)} stale asset prices")
    
    # Get the algo price once for all updates
    algo_price_usd = await get_algo_price_usd()
    
    # Update in small batches to avoid rate limiting
    batch_size = min(5, len(stale_prices))
    updated_prices = []
    
    for i in range(0, len(stale_prices), batch_size):
        batch = stale_prices[i:i+batch_size]
        update_tasks = []
        
        for asset_price in batch:
            task = update_asset_price(asset_price, current_round, algo_price_usd)
            update_tasks.append(task)
            
        # Process batch concurrently
        batch_results = await asyncio.gather(*update_tasks, return_exceptions=True)
        
        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(f"Error updating asset price for {batch[j].id}: {result}")
                updated_prices.append(batch[j])  # Keep old price on error
            else:
                updated_prices.append(result)
                
        # Small delay between batches to avoid rate limiting
        if i + batch_size < len(stale_prices):
            await asyncio.sleep(1)
    
    # Replace stale prices with updated ones in the original list
    result = []
    stale_ids = {p.id for p in stale_prices}
    updated_dict = {p.id: p for p in updated_prices}
    
    for price in asset_prices:
        if price.id in stale_ids:
            result.append(updated_dict[price.id])
        else:
            result.append(price)
            
    return result


@cached(ttl=settings.asset_prices_ttl, namespace='all_assets_price', key='happy')
async def get_all_asset_prices(current_time: datetime | None = None) -> list[AssetPriceInfo]:
    current_time = current_time or datetime.now()
    
    # Simply return all asset prices from the database without checking for staleness
    all_prices = db.asset_prices.get_all()
    return [asset_price.to_info(current_time) for asset_price in all_prices]


async def get_asset_prices_by_query(query_dict: dict, current_time: datetime | None = None) -> list[AssetPriceInfo]:
    current_time = current_time or datetime.now()
    
    # Return prices matching the query without checking for staleness
    matching_prices = db.asset_prices.get_many_by_query(query_dict)
    return [asset_price.to_info(current_time) for asset_price in matching_prices]


async def create_and_update_asset_prices() -> list[AssetPrice]:
    logger.info('Creating all asset prices.')

    all_assets = db.assets.get_all()
    asset_prices = []
    for asset in all_assets:
        try:
            asset_price = await get_asset_price_not_cached(asset.id)
            asset_prices.append(asset_price)
        except Exception as e:
            logger.error(f'Error creating asset price for {asset.id}: {e}')

    logger.info(f'{len(asset_prices)} asset prices created/updated.')
    return asset_prices
