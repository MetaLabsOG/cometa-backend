import logging

from flex import db
from flex.providers.pact import get_pact_pool_info
from flex.providers.vestige import DexProvider, fetch_lp_token
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError


logger = logging.getLogger(__name__)


def fetch_lp_token_strong(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    # TODO: refactor
    if dex_provider == DexProvider.PACT:
        pact_pool = get_pact_pool_info(asset1_id, asset2_id, lp_token_id)
        if pact_pool is None:
            logger.error(f'Pact pool for assets {asset1_id} and {asset2_id} not found')
            return fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)

        return LpToken(
            id=lp_token_id,
            pool_id=pact_pool.app_id,
            asset1_id=asset1_id,
            asset2_id=asset2_id,
            address=pact_pool.address,
            dex_provider=dex_provider
        )
    else:
        return fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)

    # elif dex_provider == DexProvider.TINYMAN_V2:
    #     tinyman_pool = get_tinyman_pool_info(asset1_id, asset2_id)
    #     return LpToken(
    #         id=lp_token_id,
    #         pool_id=None,
    #         asset1_id=asset1_id,
    #         asset2_id=asset2_id,
    #         address=tinyman_pool.address,
    #         dex_provider=dex_provider
    #     )


def fetch_lp_token_by_id(lp_token_id: int) -> LpToken:
    farming_pool = db.farming_pools.get_one(**{'stake_token.id': lp_token_id})
    if farming_pool is None:
        raise MetaError(f'Farming pool with stake asset id {lp_token_id} not found')
    return fetch_lp_token_strong(
        lp_token_id=lp_token_id,
        asset1_id=farming_pool.first_token.id,
        asset2_id=farming_pool.second_token.id,
        dex_provider=farming_pool.dex_name
    )


session_lp_tokens = {}


def get_lp_token_by_id(lp_token_id: int) -> LpToken:
    lp_token = session_lp_tokens.get(lp_token_id)
    if lp_token is None:
        lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
        if lp_token is None:
            lp_token = fetch_lp_token_by_id(lp_token_id)
            db.lp_tokens.create(lp_token)
        session_lp_tokens[lp_token_id] = lp_token
    return lp_token
