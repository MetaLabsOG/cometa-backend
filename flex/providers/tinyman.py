import logging
from dataclasses import dataclass, field
from datetime import datetime

import requests
from cachetools import cached, TTLCache
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


@dataclass_json
@dataclass
class TinymanPoolInfo:
    name: str
    lp_token_id: int | None

    asset1_id: int
    asset2_id: int

    asset1_reserve: float
    asset2_reserve: float
    total_lp_tokens: float

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    total_lp_tokens_micros: int

    address: str
    updated: datetime = field(default_factory=datetime.now)


def get_amount(micros: int, asset: Asset) -> float:
    decimals = 10 ** asset.decimals
    return micros / decimals


async def get_tinyman_pool_info(asset1_id: int, asset2_id: int) -> TinymanPoolInfo:
    if asset1_id < asset2_id:
        # Tinyman Pool class do that for some untangible issue reason
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
        lp_token_id=pool.pool_token_asset.id if pool.pool_token_asset is not None else None,
        asset1_id=pool.asset_1.id,
        asset2_id=pool.asset_2.id,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        total_lp_tokens=lp_tokens_amount,
        asset1_reserve_micros=pool.asset_1_reserves,
        asset2_reserve_micros=pool.asset_2_reserves,
        total_lp_tokens_micros=pool.issued_pool_tokens,
        address=pool.address
    )


async def fetch_algo_tinyman_pool_by_asset_id(asset_id: int) -> TinymanPoolInfo | None:
    try:
        pool = await get_tinyman_pool_info(asset_id, 0)
        return pool
    except ValueError as e:
        logger.error(f'Failed to get pool for asset {asset_id}: {e}')
        return None


@dataclass_json
@dataclass
class TinymanAssetInfo:
    id: int
    name: str
    unit_name: str
    decimals: int
    total_amount: float
    logo_svg_url: str
    logo_png_url: str


@cached(cache=TTLCache(maxsize=1, ttl=60 * 60 * 24))
def get_tinyman_assets_details() -> dict[int, TinymanAssetInfo]:
    url = 'https://asa-list.tinyman.org/assets.json'
    response = requests.get(url)
    data = response.json()
    assets_info = []
    for asa_id, asa_data in data.items():
        asset_details = TinymanAssetInfo(
            id=int(asa_id),
            name=asa_data['name'],
            unit_name=asa_data['unit_name'],
            decimals=asa_data['decimals'],
            total_amount=asa_data['total_amount'],
            logo_png_url=asa_data['logo']['png'],
            logo_svg_url=asa_data['logo']['svg']
        )
        assets_info.append(asset_details)
    return {asset.id: asset for asset in assets_info}


def get_asset_logo_url(asset_id: int) -> str:
    assets_details = get_tinyman_assets_details()
    asset = assets_details.get(asset_id)
    if asset is None:
        return settings.asset_default_logo_svg_url
    return asset.logo_svg_url
