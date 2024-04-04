from cachetools import cached, TTLCache

from env import settings
from flex import db
from flex.blockchain import get_asset_info_not_cached
from flex.data.vestige import get_lp_token_not_cached, get_asset_price_usd_not_cached
from flex.db.model.blockchain import LpToken, Asset


@cached(cache=TTLCache(maxsize=1024, ttl=settings.lp_token_prices_ttl))
def get_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
    updated_lp_token = get_lp_token_not_cached(lp_token_id, asset1_id, asset2_id, dex_provider)
    if lp_token is None:
        db.lp_tokens.create(updated_lp_token)
    else:
        db.lp_tokens.update(updated_lp_token)
    return updated_lp_token


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset(asset_id: int) -> Asset:
    asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
    updated_asset = get_asset_info_not_cached(asset_id)
    updated_asset.price_usd = get_asset_price_usd_not_cached(asset_id)
    if asset is None:
        db.assets.create(updated_asset)
    else:
        db.assets.update(updated_asset)
    return updated_asset
