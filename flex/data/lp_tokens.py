import logging

from aiocache import cached

from flex import db
from flex.blockchain.info import get_address_app_ids
from flex.providers.pact import get_pact_pool_info
from flex.providers.tinyman import get_tinyman_pool_info, TinymanPoolInfo
from flex.providers.vestige import DexProvider, fetch_lp_token
from flex.db.model.blockchain import LpToken
from flex.util import build_key_str

logger = logging.getLogger(__name__)


async def lp_token_from_tinyman_pool(tinyman_pool: TinymanPoolInfo) -> LpToken:
    app_ids = await get_address_app_ids(tinyman_pool.address)
    return LpToken(
        id=tinyman_pool.lp_token_id,
        pool_id=app_ids[0],
        asset1_id=tinyman_pool.asset1_id,
        asset2_id=tinyman_pool.asset2_id,
        address=tinyman_pool.address,
        dex_provider=DexProvider.TINYMAN_V2
    )


async def fetch_lp_token_strong(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    # TODO: refactor
    if dex_provider == DexProvider.PACT:
        pact_pool = await get_pact_pool_info(asset1_id, asset2_id, lp_token_id)
        if pact_pool is not None:
            return LpToken(
                id=lp_token_id,
                pool_id=pact_pool.app_id,
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                address=pact_pool.address,
                dex_provider=dex_provider
            )
        logger.error(f'Pact pool for assets {asset1_id} and {asset2_id} not found')

    if dex_provider == DexProvider.TINYMAN_V2 or dex_provider == DexProvider.TINYMAN:
        try:
            tinyman_pool = await get_tinyman_pool_info(asset1_id, asset2_id)
            return await lp_token_from_tinyman_pool(tinyman_pool)
        except Exception as e:
            logger.error(f'Tinyman pool for assets {asset1_id} and {asset2_id} not found: {e}')

    return await fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)


async def fetch_lp_token_by_id(lp_token_id: int) -> LpToken | None:
    farming_pool = db.farming_pools.get_one(**{'stake_token.id': lp_token_id})
    if farming_pool is None:
        return None

    return await fetch_lp_token_strong(
        lp_token_id=lp_token_id,
        asset1_id=farming_pool.first_token.id,
        asset2_id=farming_pool.second_token.id,
        dex_provider=farming_pool.dex_name
    )


@cached(ttl=60, namespace='lp_token_by_id', key_builder=build_key_str)
async def get_lp_token_by_id(lp_token_id: int) -> LpToken | None:
    lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
    if lp_token is None:
        lp_token = await fetch_lp_token_by_id(lp_token_id)
        if lp_token is not None:
            db.lp_tokens.create(lp_token)
    return lp_token
