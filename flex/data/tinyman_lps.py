"""Validated Tinyman ALGO-pool price projection."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from env import settings
from flex import db
from flex.blockchain.info import ALGO_ASSET
from flex.data.asset_prices import _upsert_asset_price
from flex.data.assets import get_asset_details
from flex.db.model.liquidity_pools import LpState
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import (
    PERSISTED_PRICE_PRECISION,
    InvalidLiquidityPoolError,
    InvalidPriceError,
    PriceQuote,
    PriceSource,
)

logger = logging.getLogger(__name__)


def _pool_observed_at(lp_state: LpState) -> datetime:
    observed_at = getattr(lp_state, "updated", None)
    if not isinstance(observed_at, datetime):
        raise InvalidLiquidityPoolError("Tinyman pool state has no observation timestamp")
    if observed_at.tzinfo is None:
        return observed_at.replace(tzinfo=UTC)
    return observed_at.astimezone(UTC)


async def _tinyman_pool_quotes(
    lp_state: LpState,
    *,
    algo_quote: PriceQuote,
) -> tuple[PriceQuote, PriceQuote, str]:
    if not lp_state.is_algo_pool or lp_state.asset2_id != ALGO_ASSET.id:
        raise InvalidLiquidityPoolError("Tinyman price source must be an asset/ALGO pool")
    if lp_state.asset1_reserve_micros <= 0 or lp_state.asset2_reserve_micros <= 0 or lp_state.total_tokens_micros <= 0:
        raise InvalidLiquidityPoolError("Tinyman reserves and issued LP supply must be positive")
    if algo_quote.asset_id != ALGO_ASSET.id:
        raise InvalidPriceError("Tinyman projection requires an ALGO/USD quote")

    asset_details = await get_asset_details(lp_state.asset1_id)
    lp_details = await get_asset_details(lp_state.token_id)
    with localcontext() as context:
        context.prec = PERSISTED_PRICE_PRECISION
        asset_reserve = Decimal(lp_state.asset1_reserve_micros) / Decimal(
            10**asset_details.decimals,
        )
        algo_reserve = Decimal(lp_state.asset2_reserve_micros) / Decimal(
            10**ALGO_ASSET.decimals,
        )
        issued_lp_tokens = Decimal(lp_state.total_tokens_micros) / Decimal(
            10**lp_details.decimals,
        )
        asset_price_algo = +(algo_reserve / asset_reserve)
        lp_price_algo = +(algo_reserve * Decimal(2) / issued_lp_tokens)
        algo_usd = algo_quote.usd

    stale_after = timedelta(seconds=settings.asset_prices_ttl)
    observed_at = min(_pool_observed_at(lp_state), algo_quote.observed_at)
    asset_quote = PriceQuote.from_raw(
        asset_id=lp_state.asset1_id,
        algo=asset_price_algo,
        usd=asset_price_algo * algo_usd,
        source=PriceSource.TINYMAN,
        stale_after=stale_after,
        observed_round=lp_state.last_updated_round,
        observed_at=observed_at,
    )
    lp_quote = PriceQuote.from_raw(
        asset_id=lp_state.token_id,
        algo=lp_price_algo,
        usd=lp_price_algo * algo_usd,
        source=PriceSource.DERIVED_LP,
        stale_after=stale_after,
        observed_round=lp_state.last_updated_round,
        observed_at=observed_at,
    )
    return asset_quote, lp_quote, asset_details.name


async def update_tinyman_algo_lp_state_and_prices(
    lp_state: LpState,
    algo_quote: PriceQuote,
) -> AssetPrice:
    """Project one validated Tinyman observation into LP and asset read models."""

    asset_quote, lp_quote, asset_name = await _tinyman_pool_quotes(
        lp_state,
        algo_quote=algo_quote,
    )
    lp_state.token_price_algo = lp_quote.to_legacy_floats()[0]
    db.lp_states.update(lp_state)

    price_algo, price_usd = asset_quote.to_legacy_floats()
    asset_price = AssetPrice(
        id=asset_quote.asset_id,
        price_algo=price_algo,
        price_usd=price_usd,
        last_update_round=asset_quote.observed_round or 0,
        tinyman_algo_pool_id=lp_state.id,
        name=asset_name,
        source=asset_quote.source.value,
        observed_at=asset_quote.observed_at,
    )
    _upsert_asset_price(asset_price)
    logger.debug(
        "Updated asset %s from Tinyman ALGO pool %s: algo=%s, usd=%s",
        asset_price.id,
        lp_state.id,
        asset_price.price_algo,
        asset_price.price_usd,
    )
    return asset_price
