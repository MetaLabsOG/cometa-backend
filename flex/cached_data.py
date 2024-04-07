from cachetools import cached, TTLCache

from env import settings
from flex import db
from flex.data.lp_tokens import fetch_lp_token
from flex.db.model.blockchain import LpToken, Asset


@cached(cache=TTLCache(maxsize=1024, ttl=settings.lp_token_prices_ttl))
def get_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
    updated_lp_token = fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)
    if lp_token is None:
        db.lp_tokens.create(updated_lp_token)
    else:
        db.lp_tokens.update(updated_lp_token)
    return updated_lp_token
