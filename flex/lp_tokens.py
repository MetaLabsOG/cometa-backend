from cachetools import cached, TTLCache

from env import settings
from flex.tinyman import get_tinyman_pool_info
from flex.vestige import get_asset_price_usd


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_lp_price(asset1_id: int, asset2_id: int) -> float | None:
    tinyman_pool = get_tinyman_pool_info(asset1_id, asset2_id)
    if tinyman_pool.lp_tokens_amount == 0:
        return None

    asset1_price = get_asset_price_usd(asset1_id)
    asset2_price = get_asset_price_usd(asset2_id)
    total_cost = asset1_price * tinyman_pool.asset1_reserve + asset2_price * tinyman_pool.asset2_reserve
    lp_token_price = total_cost / tinyman_pool.lp_tokens_amount
    return lp_token_price
