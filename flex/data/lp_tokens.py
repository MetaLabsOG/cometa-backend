import logging

from aiocache import cached

from flex import db
from flex.blockchain.info import get_address_app_ids
from flex.db.model.blockchain import LpToken
from flex.providers import vestige
from flex.providers.pact import get_pact_pool_info
from flex.providers.tinyman import TinymanPoolInfo, get_tinyman_pool_info
from flex.providers.vestige import DexProvider, fetch_lp_token
from flex.util import build_key_str

logger = logging.getLogger(__name__)


class LpTokenIdentityConflictError(RuntimeError):
    """Raised when an ASA ID is already bound to different pool metadata."""


def persist_lp_token(candidate: LpToken) -> LpToken:
    """Atomically register an LP token and verify its immutable identity."""

    persisted = db.lp_tokens.get_or_create(candidate)
    identity_fields = (
        "id",
        "pool_id",
        "asset1_id",
        "asset2_id",
        "address",
        "dex_provider",
    )
    if tuple(getattr(persisted, field) for field in identity_fields) != tuple(
        getattr(candidate, field) for field in identity_fields
    ):
        raise LpTokenIdentityConflictError(
            f"LP token {candidate.id} is already registered with different pool metadata"
        )
    return persisted


async def lp_token_from_tinyman_pool(tinyman_pool: TinymanPoolInfo) -> LpToken:
    app_ids = await get_address_app_ids(tinyman_pool.address)
    return LpToken(
        id=tinyman_pool.lp_token_id,
        pool_id=app_ids[0],
        asset1_id=tinyman_pool.asset1_id,
        asset2_id=tinyman_pool.asset2_id,
        address=tinyman_pool.address,
        dex_provider=DexProvider.TINYMAN_V2,
    )


async def fetch_lp_token_strong(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    if dex_provider == DexProvider.PACT:
        pact_pool = await get_pact_pool_info(asset1_id, asset2_id, lp_token_id)
        if pact_pool is not None:
            return LpToken(
                id=lp_token_id,
                pool_id=pact_pool.app_id,
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                address=pact_pool.address,
                dex_provider=dex_provider,
            )
        else:
            return await vestige.fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)

    if dex_provider == DexProvider.TINYMAN_V2 or dex_provider == DexProvider.TINYMAN:
        try:
            tinyman_pool = await get_tinyman_pool_info(asset1_id, asset2_id)
            return await lp_token_from_tinyman_pool(tinyman_pool)
        except Exception as e:
            logger.error(f"Tinyman pool for assets {asset1_id} and {asset2_id} not found: {e}")

    return await fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)


async def fetch_lp_token_by_id(lp_token_id: int) -> LpToken | None:
    farming_pool = db.farming_pools.get_one(**{"stake_token.id": lp_token_id})
    if farming_pool is None:
        return None

    if farming_pool.first_token.id < farming_pool.second_token.id:
        farming_pool.first_token.id, farming_pool.second_token.id = (
            farming_pool.second_token.id,
            farming_pool.first_token.id,
        )

    return await fetch_lp_token_strong(
        lp_token_id=lp_token_id,
        asset1_id=farming_pool.first_token.id,
        asset2_id=farming_pool.second_token.id,
        dex_provider=farming_pool.dex_name,
    )


@cached(namespace="lp_token_get_all", key_builder=build_key_str)
async def get_all_lp_tokens() -> list[LpToken]:
    return db.lp_tokens.get_all()


@cached(namespace="lp_token_by_id", key_builder=build_key_str)
async def get_lp_token_by_id(lp_token_id: int) -> LpToken | None:
    lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
    if lp_token is None:
        lp_token = await fetch_lp_token_by_id(lp_token_id)
        if lp_token is not None:
            lp_token = persist_lp_token(lp_token)
    return lp_token
