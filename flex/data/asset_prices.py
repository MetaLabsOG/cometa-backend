import logging

from cachetools import cached, TTLCache

from env import settings
from flex import db
from flex.blockchain.info import get_current_round, ALGO_ASSET
from flex.data.assets import micros_to_amount
from flex.data.lp_states import get_tinyman_pool_lp_state_by_asset_id, get_priced_lp_state_by_lp_token_id
from flex.data.lp_tokens import get_lp_token_by_id
from flex.db.model.blockchain import LpToken
from flex.db.model.liquidity_pools import LpState
from flex.db.model.priced import AssetPrice, AssetPriceInfo
from flex.providers.vestige import get_full_asset_price, get_algo_price_usd

logger = logging.getLogger(__name__)


def calculate_algo_price_from_tiny_algo_pool(lp_state: LpState) -> float:
    if lp_state.asset1_id < lp_state.asset2_id:
        lp_state.asset1_id, lp_state.asset2_id = lp_state.asset2_id, lp_state.asset1_id
        lp_state.asset1_reserve_micros, lp_state.asset2_reserve_micros = lp_state.asset2_reserve_micros, lp_state.asset1_reserve_micros
        db.lp_states.update(lp_state)

    if lp_state.asset2_id != ALGO_ASSET.id:
        raise ValueError(f'Not an ALGO pool: {lp_state}')

    return micros_to_amount(lp_state.asset2_id, lp_state.asset2_reserve_micros) / micros_to_amount(
        lp_state.asset1_id, lp_state.asset1_reserve_micros)


def create_asset_price(asset_id: int) -> AssetPrice:
    lp_state = get_tinyman_pool_lp_state_by_asset_id(asset_id)
    if lp_state is not None:
        logger.info(f'Price for {asset_id}: Tinyman pool {lp_state.asset1_id}/{lp_state.asset2_id}')
        price_algo = calculate_algo_price_from_tiny_algo_pool(lp_state)
        asset_price = AssetPrice(
            id=asset_id,
            price_algo=price_algo,
            price_usd=price_algo * get_algo_price_usd(),  # TODO: refactor to use USDC/ALGO pool
            last_update_round=lp_state.last_updated_round,
            tinyman_algo_pool_id=lp_state.id
        )
    else:
        price = get_full_asset_price(asset_id)
        asset_price = AssetPrice(
            id=asset_id,
            price_algo=price.algo,
            price_usd=price.usd,
            last_update_round=get_current_round()
        )
    db.asset_prices.create(asset_price)
    logger.info(f'New Asset Price: {asset_price}')
    return asset_price


def update_asset_price(asset_price: AssetPrice) -> AssetPrice:
    if asset_price.tinyman_algo_pool_id is not None:
        lp_state = db.lp_states.get_one(id=asset_price.tinyman_algo_pool_id)
        if lp_state is not None:
            asset_price.price_algo = calculate_algo_price_from_tiny_algo_pool(lp_state)
            asset_price.price_usd = asset_price.price_algo * get_algo_price_usd()
        else:
            price = get_full_asset_price(asset_id=asset_price.id)
            asset_price.price_algo = price.algo
            asset_price.price_usd = price.usd

    asset_price.last_updated_round = get_current_round()
    db.asset_prices.update(asset_price)

    logger.debug(f'Updated Asset Price: {asset_price}')
    return asset_price


def calculate_lp_token_price(lp_token: LpToken, asset_price: AssetPrice | None) -> AssetPrice:
    priced_lp_state = get_priced_lp_state_by_lp_token_id(lp_token.id)
    if asset_price is None:
        asset_price = AssetPrice(
            id=lp_token.id,
            price_algo=priced_lp_state.token_price_algo,
            price_usd=priced_lp_state.token_price_usd,
            last_update_round=priced_lp_state.last_updated_round
        )
        db.asset_prices.create(asset_price)
    else:
        asset_price.price_algo = priced_lp_state.token_price_algo
        asset_price.price_usd = priced_lp_state.token_price_usd
        asset_price.last_updated_round = priced_lp_state.last_updated_round
        db.asset_prices.update(asset_price)
    return asset_price


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset_price(asset_id: int) -> AssetPrice:
    asset_price = db.asset_prices.get_one(id=asset_id)

    lp_token = get_lp_token_by_id(asset_id)
    if lp_token is not None:
        return calculate_lp_token_price(lp_token, asset_price)

    if asset_price is None:
        asset_price = create_asset_price(asset_id)
    else:
        asset_price = update_asset_price(asset_price)
    return asset_price


@cached(cache=TTLCache(maxsize=1, ttl=settings.asset_prices_ttl))
def get_all_asset_prices() -> list[AssetPriceInfo]:
    return [asset_price.to_info() for asset_price in db.asset_prices.get_all()]
