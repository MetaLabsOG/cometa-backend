import logging
from datetime import datetime

from aiocache import cached

from env import settings
from flex import db
from flex.blockchain.info import get_current_round
from flex.data.assets import get_asset_details
from flex.data.lp_states import get_tinyman_pool_lp_state_by_asset_id, \
    get_lp_state_by_lp_token_id
from flex.data.lp_tokens import get_lp_token_by_id
from flex.data.tinyman_lps import calculate_price_algo_from_tiny_algo_pool
from flex.db.model.priced import AssetPrice, AssetPriceInfo
from flex.providers.vestige import vestige_full_asset_price, get_algo_price_usd, DexProvider

logger = logging.getLogger(__name__)


async def create_asset_price(asset_id: int, current_round: int, algo_price_usd: float | None = None) -> AssetPrice:
    asset_details = await get_asset_details(asset_id)
    logger.debug(f'Creating asset price {asset_id} = {asset_details.name}')

    algo_price_usd = algo_price_usd or await get_algo_price_usd()
    lp_token = await get_lp_token_by_id(asset_id)
    if lp_token is not None:
        # TODO: optimize
        priced_lp_state = await get_lp_state_by_lp_token_id(lp_token.id)
        asset_price = AssetPrice(
            id=lp_token.id,
            name=asset_details.name,
            price_algo=priced_lp_state.token_price_algo,
            price_usd=priced_lp_state.token_price_algo * algo_price_usd,
            last_update_round=priced_lp_state.last_updated_round
        )
    else:
        asset_price = await get_simple_asset_price_from_pools(asset_id, algo_price_usd)
        if asset_price is None:
            price = await vestige_full_asset_price(asset_id)
            asset_price = AssetPrice(
                id=asset_id,
                name=asset_details.name,
                price_algo=price.algo,
                price_usd=price.usd,
                last_update_round=current_round
            )
    db.asset_prices.create(asset_price)
    logger.info(f'\nNew Asset Price ${asset_price.name}: usd = {asset_price.price_usd}, algo = {asset_price.price_algo}\n')
    return asset_price


async def get_simple_asset_price_from_pools(asset_id: int, algo_price_usd: float | None = None) -> AssetPrice | None:
    tiny_lp_state = await get_tinyman_pool_lp_state_by_asset_id(asset_id)
    if tiny_lp_state is None:
        return None

    price_algo = await calculate_price_algo_from_tiny_algo_pool(tiny_lp_state)
    algo_price_usd = algo_price_usd or (await get_algo_price_usd())
    asset_price = AssetPrice(
        id=asset_id,
        name=(await get_asset_details(asset_id)).name,
        price_algo=price_algo,
        price_usd=price_algo * algo_price_usd,
        last_update_round=tiny_lp_state.last_updated_round,
        tinyman_algo_pool_id=tiny_lp_state.id
    )
    return asset_price


async def update_asset_price(asset_price: AssetPrice, current_round: int, algo_price_usd: float | None = None) -> AssetPrice:
    logger.debug(f'Updating Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')

    lp_token = await get_lp_token_by_id(asset_price.id)
    algo_price_usd = algo_price_usd or (await get_algo_price_usd())
    if lp_token is not None:
        priced_lp_state = await get_lp_state_by_lp_token_id(lp_token.id)
        asset_price.price_algo = priced_lp_state.token_price_algo
        asset_price.price_usd = priced_lp_state.token_price_algo * algo_price_usd

    elif asset_price.tinyman_algo_pool_id is not None:
        lp_state = db.lp_states.get_one(id=asset_price.tinyman_algo_pool_id)
        if lp_state is not None and lp_state.dex_provider == DexProvider.TINYMAN_V2:
            asset_price.price_algo = await calculate_price_algo_from_tiny_algo_pool(lp_state)
            asset_price.price_usd = asset_price.price_algo * algo_price_usd
        else:
            price = await vestige_full_asset_price(asset_id=asset_price.id)
            asset_price.price_algo = price.algo
            asset_price.price_usd = price.usd

    asset_price.last_updated_round = current_round
    db.asset_prices.update(asset_price)

    logger.debug(f'Fresh Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')
    return asset_price


@cached(ttl=settings.asset_prices_ttl, namespace='asset_price', key='asset_id')
async def get_asset_price(asset_id: int) -> AssetPrice:
    return await get_asset_price_not_cached(asset_id)


async def get_asset_price_not_cached(asset_id: int) -> AssetPrice:
    asset_price = db.asset_prices.get_one(id=asset_id)
    current_round = await get_current_round()
    if asset_price is None:
        asset_price = await create_asset_price(asset_id, current_round)
    elif current_round - asset_price.last_update_round > settings.asset_prices_ttl:
        asset_price = await update_asset_price(asset_price, current_round)
    return asset_price


@cached(ttl=settings.asset_prices_ttl, namespace='all_assets_price', key='happy')
async def get_all_asset_prices(current_time: datetime | None = None) -> list[AssetPriceInfo]:
    current_time = current_time or datetime.now()
    return [asset_price.to_info(current_time) for asset_price in db.asset_prices.get_all()]


async def get_asset_prices_by_query(query_dict: dict, current_time: datetime | None = None) -> list[AssetPriceInfo]:
    return [asset_price.to_info(current_time) for asset_price in db.asset_prices.get_many_by_query(query_dict)]


async def create_and_update_asset_prices() -> list[AssetPrice]:
    logger.info('Creating all asset prices.')

    all_assets = db.assets.get_all()
    asset_prices = []
    for asset in all_assets:
        try:
            asset_price = await get_asset_price_not_cached(asset.id)
            asset_prices.append(asset_price)
        except Exception as e:
            logger.error(f'Error creating asset price for {asset.id}: {e}')

    logger.info(f'{len(asset_prices)} asset prices created/updated.')
    return asset_prices
