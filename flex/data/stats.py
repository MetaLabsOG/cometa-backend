import logging
from datetime import timedelta

from env import settings
from flex import db
from flex.data.asset_prices import get_asset_price, validated_stored_asset_price
from flex.db.model.pools import PoolType

logger = logging.getLogger(__name__)


async def calculate_total_tvl_usd_for_type(type: PoolType) -> float:
    pools = db.pool_states.get_many(type=type)
    all_asset_prices = db.asset_prices.get_all()
    max_age = timedelta(seconds=settings.asset_prices_max_stale)
    price_usd_by_id = {
        price.id: price.price_usd
        for price in all_asset_prices
        if validated_stored_asset_price(price, max_age=max_age) is not None
    }
    total_usd = 0
    for pool in pools:
        pool_token_price_usd = price_usd_by_id.get(pool.stake_token.id)
        if pool_token_price_usd is None:
            pool_token_price_usd = (await get_asset_price(pool.stake_token.id)).price_usd
        if pool.total_staked < 0:
            logger.warning(f'Negative total_staked in pool {pool.pool_id}: {pool.total_staked}')
        total_usd += pool.total_staked * pool_token_price_usd
    return total_usd


async def calculate_total_tvl_usd() -> dict:
    farm_tvl = await calculate_total_tvl_usd_for_type(PoolType.FARMING)
    stake_tvl = await calculate_total_tvl_usd_for_type(PoolType.STAKING)
    return {
        'farming': farm_tvl,
        'staking': stake_tvl,
        'total': farm_tvl + stake_tvl
    }
