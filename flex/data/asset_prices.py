import logging

from aiocache import cached

from env import settings
from flex import db
from flex.blockchain.info import get_current_round, ALGO_ASSET
from flex.data.assets import micros_to_amount, get_asset_details
from flex.data.lp_states import get_tinyman_pool_lp_state_by_asset_id, get_priced_lp_state_by_lp_token_id
from flex.data.lp_tokens import get_lp_token_by_id
from flex.db.model.liquidity_pools import LpState
from flex.db.model.priced import AssetPrice
from flex.providers.vestige import get_full_asset_price, get_algo_price_usd
from flex.sync_state import is_sync_delayed

logger = logging.getLogger(__name__)


def is_algo_pool(lp_state: LpState) -> bool:
    return lp_state.asset2_id == ALGO_ASSET.id


async def calculate_algo_price_from_tiny_algo_pool(lp_state: LpState) -> float:
    if lp_state.asset1_id < lp_state.asset2_id:
        lp_state.asset1_id, lp_state.asset2_id = lp_state.asset2_id, lp_state.asset1_id
        lp_state.asset1_reserve_micros, lp_state.asset2_reserve_micros = lp_state.asset2_reserve_micros, lp_state.asset1_reserve_micros
        db.lp_states.update(lp_state)

    if lp_state.asset1_reserve_micros == 0:
        return 0

    if not is_algo_pool(lp_state):
        raise ValueError(f'Not an ALGO pool: {lp_state}')

    asset2_amount = await micros_to_amount(lp_state.asset2_id, lp_state.asset2_reserve_micros)
    asset1_amount = await micros_to_amount(lp_state.asset1_id, lp_state.asset1_reserve_micros)
    return asset2_amount / asset1_amount


async def create_asset_price_from_tinyman_lp_state(lp_state: LpState, algo_price_usd: float | None = None) -> AssetPrice:
    logger.debug(f'Creating asset price from Tinyman pool {lp_state.asset1_id}/{lp_state.asset2_id}')
    asset_price_algo = await calculate_algo_price_from_tiny_algo_pool(lp_state)
    algo_price_usd = algo_price_usd or get_algo_price_usd()
    asset_price = AssetPrice(
        id=lp_state.asset1_id,
        name=(await get_asset_details(lp_state.asset1_id)).name,
        price_algo=asset_price_algo,
        price_usd=asset_price_algo * algo_price_usd,
        last_update_round=lp_state.last_updated_round,
        tinyman_algo_pool_id=lp_state.id
    )
    db.asset_prices.create(asset_price)
    logger.info(f'New Asset Price: {asset_price}')
    return asset_price


async def create_asset_price(asset_id: int, algo_price_usd: float | None = None) -> AssetPrice:
    logger.debug(f'Creating asset price {asset_id}')

    lp_token = await get_lp_token_by_id(asset_id)
    if lp_token is not None:
        # TODO: optimize
        priced_lp_state = await get_priced_lp_state_by_lp_token_id(lp_token.id)
        asset_price = AssetPrice(
            id=lp_token.id,
            name=(await get_asset_details(lp_token.id)).name,
            price_algo=priced_lp_state.token_price_algo,
            price_usd=priced_lp_state.token_price_usd,
            last_update_round=priced_lp_state.last_updated_round
        )

    else:
        lp_state = await get_tinyman_pool_lp_state_by_asset_id(asset_id)
        if lp_state is not None:
            logger.info(f'Price for {asset_id}: Tinyman pool {lp_state.asset1_id}/{lp_state.asset2_id}')
            price_algo = await calculate_algo_price_from_tiny_algo_pool(lp_state)
            algo_price_usd = algo_price_usd or (await get_algo_price_usd())
            asset_price = AssetPrice(
                id=asset_id,
                name=(await get_asset_details(asset_id)).name,
                price_algo=price_algo,
                price_usd=price_algo * algo_price_usd,  # TODO: refactor to use USDC/ALGO pool
                last_update_round=lp_state.last_updated_round,
                tinyman_algo_pool_id=lp_state.id
            )
        else:
            price = await get_full_asset_price(asset_id)
            asset_price = AssetPrice(
                id=asset_id,
                name=(await get_asset_details(asset_id)).name,
                price_algo=price.algo,
                price_usd=price.usd,
                last_update_round=await get_current_round()
            )
    db.asset_prices.create(asset_price)
    logger.info(f'\nNew Asset Price ${asset_price.name}: usd = {asset_price.price_usd}, algo = {asset_price.price_algo}\n')
    return asset_price


async def update_asset_price(asset_price: AssetPrice, algo_price_usd: float | None = None) -> AssetPrice:
    logger.debug(f'Updating Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')

    lp_token = await get_lp_token_by_id(asset_price.id)
    if lp_token is not None:
        priced_lp_state = await get_priced_lp_state_by_lp_token_id(lp_token.id)
        asset_price.price_algo = priced_lp_state.token_price_algo
        asset_price.price_usd = priced_lp_state.token_price_usd

    elif asset_price.tinyman_algo_pool_id is not None:
        lp_state = db.lp_states.get_one(id=asset_price.tinyman_algo_pool_id)
        if lp_state is not None:
            algo_price_usd = algo_price_usd or (await get_algo_price_usd())
            asset_price.price_algo = await calculate_algo_price_from_tiny_algo_pool(lp_state)
            asset_price.price_usd = asset_price.price_algo * algo_price_usd
        else:
            price = await get_full_asset_price(asset_id=asset_price.id)
            asset_price.price_algo = price.algo
            asset_price.price_usd = price.usd

    asset_price.last_updated_round = await get_current_round()
    db.asset_prices.update(asset_price)

    logger.debug(f'Fresh Asset Price id = {asset_price.id}, algo_price = {asset_price.price_algo}')
    return asset_price


async def update_asset_price_with_lp_state(lp_state: LpState, algo_price_usd: float | None = None) -> AssetPrice | None:
    if not is_algo_pool(lp_state):
        return None
    logger.debug(f'Updating "{lp_state.asset1_id}" price with Tiny ALGO pool {lp_state.id}')

    asset_price = db.asset_prices.get_one(id=lp_state.asset1_id)
    if asset_price is None:
        asset_price = await create_asset_price_from_tinyman_lp_state(lp_state, algo_price_usd)
    else:
        asset_price.price_algo = await calculate_algo_price_from_tiny_algo_pool(lp_state)
        asset_price.price_usd = asset_price.price_algo * algo_price_usd
        asset_price.last_update_round = lp_state.last_updated_round
        db.asset_prices.update(asset_price)
    return asset_price


@cached(ttl=settings.asset_prices_ttl, namespace='asset_price', key='asset_id')
async def get_asset_price(asset_id: int) -> AssetPrice:
    asset_price = db.asset_prices.get_one(id=asset_id)
    if asset_price is None:
        asset_price = await create_asset_price(asset_id)
    elif (await is_sync_delayed()):
        asset_price = await update_asset_price(asset_price)
    return asset_price


@cached(ttl=settings.asset_prices_ttl, namespace='all_assets_price', key='happy')
async def get_all_asset_prices() -> list[AssetPrice]:
    return db.asset_prices.get_all()


async def create_and_update_asset_prices() -> list[AssetPrice]:
    logger.info('Creating all asset prices.')

    all_assets = db.assets.get_all()
    asset_prices = []
    for asset in all_assets:
        try:
            asset_price = await get_asset_price(asset.id)
            asset_prices.append(asset_price)
        except Exception as e:
            logger.error(f'Error creating asset price for {asset.id}: {e}')

    logger.info(f'{len(asset_prices)} asset prices created/updated.')
    return asset_prices
