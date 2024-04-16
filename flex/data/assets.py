import logging

from aiocache import cached

from flex import db
from flex.blockchain.info import fetch_asset, ALGO_ASSET
from flex.db.model.blockchain import Asset, AssetInfo, AssetDetails
from flex.util import build_key_str

logger = logging.getLogger(__name__)


@cached(namespace='full_asset', key_builder=build_key_str)
async def get_full_asset(asset_id: int) -> Asset:
    asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
    if asset is None:
        asset = await fetch_asset(asset_id)
        db.assets.create(asset)
        logger.info(f'New Asset: id={asset.id}, name={asset.name}')
    return asset


@cached(namespace='asset_info', key_builder=build_key_str)
async def get_asset_info(asset_id: int) -> AssetInfo:
    return (await get_full_asset(asset_id)).to_info()


@cached(namespace='asset_details', key_builder=build_key_str)
async def get_asset_details(asset_id: int) -> AssetDetails:
    return (await get_full_asset(asset_id)).to_details()


@cached(ttl=20, namespace='all_asset_details', key='420')
async def get_all_asset_details() -> list[AssetDetails]:
    all_assets = db.assets.get_all()
    return [asset.to_details() for asset in all_assets]


async def micros_to_amount(asset_id: int, amount_micros: int) -> float:
    return (await get_full_asset(asset_id)).micros_to_amount(amount_micros)


async def amount_to_micros(asset_id: int, amount: float) -> int:
    return (await get_full_asset(asset_id)).amount_to_micros(amount)


async def load_all_assets_data() -> list[Asset]:
    logger.info('Loading all assets data.')

    asset_ids = {ALGO_ASSET.id}

    for pool in db.farming_pools.get_all():
        asset_ids.add(pool.stake_token.id)
        asset_ids.add(pool.reward_token.id)
        asset_ids.add(pool.first_token.id)
        asset_ids.add(pool.second_token.id)

    for pool in db.staking_pools.get_all():
        asset_ids.add(pool.stake_token.id)
        asset_ids.add(pool.reward_token.id)

    assets = []
    for asset_id in asset_ids:
        asset = await get_full_asset(asset_id)
        assets.append(asset)

    logger.info(f'{len(asset_ids)} assets data loaded.')
    return assets
