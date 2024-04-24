import logging

from flex import db
from flex.blockchain.info import ALGO_ASSET
from flex.data.assets import micros_to_amount
from flex.db.model.liquidity_pools import LpState
from flex.db.model.priced import AssetPrice
from flex.providers.vestige import get_algo_price_usd

logger = logging.getLogger(__name__)


async def calculate_price_algo_from_tiny_algo_pool(lp_state: LpState) -> float:
    if not lp_state.is_algo_pool:
        raise ValueError(f'Not an ALGO pool: {lp_state}')

    if lp_state.asset1_id < lp_state.asset2_id:
        lp_state.asset1_id, lp_state.asset2_id = lp_state.asset2_id, lp_state.asset1_id
        lp_state.asset1_reserve_micros, lp_state.asset2_reserve_micros = lp_state.asset2_reserve_micros, lp_state.asset1_reserve_micros
        db.lp_states.update(lp_state)

    if lp_state.asset1_reserve_micros == 0:
        return 0

    # TODO: use new fields after migration
    asset2_amount = await micros_to_amount(lp_state.asset2_id, lp_state.asset2_reserve_micros)
    asset1_amount = await micros_to_amount(lp_state.asset1_id, lp_state.asset1_reserve_micros)
    return asset2_amount / asset1_amount


async def create_asset_price_from_tinyman_algo_lp_state(
        lp_state: LpState,
        algo_price_usd: float | None = None
) -> AssetPrice:
    if db.asset_prices.exists(id=lp_state.asset1_id):
        raise ValueError(f'Asset price already exists: {lp_state.asset1_id}')
    logger.debug(f'Creating asset price from Tinyman pool {lp_state.id}: {lp_state.asset1_id}/{lp_state.asset2_id}')

    asset_price_algo = await calculate_price_algo_from_tiny_algo_pool(lp_state)
    algo_price_usd = algo_price_usd or await get_algo_price_usd()
    asset_price = AssetPrice(
        id=lp_state.asset1_id,
        price_algo=asset_price_algo,
        price_usd=asset_price_algo * algo_price_usd,
        last_update_round=lp_state.last_updated_round,
        tinyman_algo_pool_id=lp_state.id
    )
    db.asset_prices.create(asset_price)

    logger.info(f'New Asset Price: {asset_price}')
    return asset_price


async def update_algo_tinyman_lp_assets_price(lp_state: LpState, algo_price_usd: float | None = None) -> AssetPrice:
    if not lp_state.is_algo_pool:
        raise ValueError(f'Not an ALGO pool: {lp_state}')
    logger.debug(f'Updating "{lp_state.asset1_id}" price with Tiny ALGO pool {lp_state.id}')

    algo_price_usd = algo_price_usd or await get_algo_price_usd()
    asset_id = lp_state.asset1_id if lp_state.asset1_id != ALGO_ASSET.id else lp_state.asset2_id
    asset_price = db.asset_prices.get_one(id=asset_id)
    if asset_price is None:
        asset_price = await create_asset_price_from_tinyman_algo_lp_state(lp_state, algo_price_usd)
    else:
        asset_price.price_algo = await calculate_price_algo_from_tiny_algo_pool(lp_state)
        asset_price.price_usd = asset_price.price_algo * algo_price_usd
        asset_price.last_update_round = lp_state.last_updated_round
        db.asset_prices.update(asset_price)

    return asset_price

