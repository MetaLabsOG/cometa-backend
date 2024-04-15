import logging
from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json
from tinyman.assets import Asset
from tinyman.v2.client import TinymanV2MainnetClient, TinymanV2TestnetClient

from env import settings
from flex.blockchain.base import algod_client, cometa_public_key

if settings.is_mainnet():
    tinyman_client = TinymanV2MainnetClient(algod_client=algod_client, user_address=cometa_public_key)
else:
    tinyman_client = TinymanV2TestnetClient(algod_client=algod_client, user_address=cometa_public_key)

logger = logging.getLogger(__name__)


def get_amount(micros: int, asset: Asset) -> float:
    decimals = 10 ** asset.decimals
    return micros / decimals


def get_micros(amount: float, asset: Asset) -> int:
    decimals = 10 ** asset.decimals
    return int(amount * decimals)


@dataclass_json
@dataclass
class TinymanPoolInfo:
    name: str

    asset1_reserve: float
    asset2_reserve: float
    total_lp_tokens: float

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    total_lp_tokens_micros: int

    address: str
    updated: datetime = field(default_factory=datetime.now)


def get_tinyman_pool_info(asset1_id: int, asset2_id: int) -> TinymanPoolInfo:
    if asset1_id < asset2_id:
        # Tinyman Pool class do that for some untangible fucking reason
        asset1_id, asset2_id = asset2_id, asset1_id

    # assets are already cached inside TinymanClient
    asset1 = tinyman_client.fetch_asset(asset1_id)
    asset2 = tinyman_client.fetch_asset(asset2_id)

    pool = tinyman_client.fetch_pool(asset1, asset2)

    logger.debug(f'Found pool for assets {asset1_id} and {asset2_id}: {pool}')
    if pool.asset_1_reserves is None or pool.asset_2_reserves is None or pool.issued_pool_tokens is None:
        raise ValueError(f'Tinyman pool for assets {asset1_id} and {asset2_id} is empty: {pool}')

    asset1_reserve = get_amount(pool.asset_1_reserves, pool.asset_1)
    asset2_reserve = get_amount(pool.asset_2_reserves, pool.asset_2)
    lp_tokens_amount = get_amount(pool.issued_pool_tokens, pool.pool_token_asset)

    return TinymanPoolInfo(
        name=pool.pool_token_asset.name,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        total_lp_tokens=lp_tokens_amount,
        asset1_reserve_micros=pool.asset_1_reserves,
        asset2_reserve_micros=pool.asset_2_reserves,
        total_lp_tokens_micros=pool.issued_pool_tokens,
        address=pool.address
    )
