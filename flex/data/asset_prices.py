import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from aiocache import cached
from algosdk.error import AlgodHTTPError, IndexerHTTPError
from pymongo.errors import DuplicateKeyError, PyMongoError

from env import settings
from flex import db
from flex.application.price_refresh import (
    PriceRefreshError,
    fetch_vestige_price_quote,
    validate_provider_quote,
)
from flex.blockchain.info import get_current_round
from flex.data.assets import get_asset_details
from flex.db.model.priced import AssetPrice, AssetPriceInfo
from flex.domain.pricing import (
    PriceQuote,
    PriceSource,
    PriceUnavailableError,
    PricingError,
    is_observation_stale,
)
from flex.util import build_key_str

logger = logging.getLogger(__name__)


def _price_freshness_window() -> timedelta:
    return timedelta(seconds=settings.asset_prices_ttl)


def _price_max_stale_window() -> timedelta:
    return timedelta(seconds=settings.asset_prices_max_stale)


def _asset_price_from_quote(
    quote: PriceQuote,
    *,
    name: str,
    current_round: int,
) -> AssetPrice:
    price_algo, price_usd = quote.to_legacy_floats()
    return AssetPrice(
        id=quote.asset_id,
        name=name,
        price_algo=price_algo,
        price_usd=price_usd,
        last_update_round=quote.observed_round if quote.observed_round is not None else current_round,
        source=quote.source.value,
        observed_at=quote.observed_at,
    )


def is_asset_price_stale(
    asset_price: AssetPrice,
    *,
    now: datetime | None = None,
    fresh_for: timedelta | None = None,
) -> bool:
    """Return whether a stored observation is older than the wall-clock policy."""

    observed_at = asset_price.observed_at or asset_price.updated
    return is_observation_stale(
        observed_at,
        fresh_for=fresh_for if fresh_for is not None else _price_freshness_window(),
        now=now,
    )


def validated_stored_asset_price(
    asset_price: AssetPrice,
    *,
    max_age: timedelta,
    now: datetime | None = None,
) -> AssetPrice | None:
    """Return a stored price only when its values and age satisfy policy."""

    current_time = now or datetime.now(UTC)
    if is_asset_price_stale(
        asset_price,
        now=current_time,
        fresh_for=max_age,
    ):
        return None

    observed_at = asset_price.observed_at or asset_price.updated
    try:
        quote = PriceQuote.from_raw(
            asset_id=asset_price.id,
            algo=asset_price.price_algo,
            usd=asset_price.price_usd,
            source=PriceSource.DATABASE,
            observed_at=observed_at,
            observed_round=asset_price.last_update_round,
            stale_after=max_age,
        )
        quote.to_legacy_floats()
    except (AttributeError, PricingError, TypeError, ValueError) as exc:
        logger.warning(
            "Ignoring invalid stored price for asset %s: %s",
            getattr(asset_price, "id", "unknown"),
            exc,
        )
        return None
    return asset_price


def _skip_asset_price_cache(asset_price: AssetPrice) -> bool:
    """Avoid caching a fallback beyond its maximum stale window."""

    cache_safe_seconds = settings.asset_prices_max_stale - settings.asset_prices_ttl
    if cache_safe_seconds <= 0:
        return True
    return (
        validated_stored_asset_price(
            asset_price,
            max_age=timedelta(seconds=cache_safe_seconds),
        )
        is None
    )


def _upsert_asset_price(asset_price: AssetPrice) -> bool:
    """Persist a quote only if it is not older than the stored observation."""

    if not isinstance(asset_price.observed_at, datetime):
        raise PricingError("persisted asset prices require an observation timestamp")

    asset_price.updated = datetime.now(UTC)
    doc = asset_price.to_dict()
    doc.pop("_id", None)
    created = doc.pop("created", asset_price.created)
    collection = db.asset_prices.mongodb_collection
    selector = {
        "id": asset_price.id,
        "$or": [
            {"observed_at": {"$exists": False}},
            {"observed_at": None},
            {"observed_at": {"$lte": asset_price.observed_at}},
        ],
    }
    result = collection.update_one(
        selector,
        {"$set": doc, "$setOnInsert": {"created": created}},
        upsert=False,
    )
    if result.matched_count:
        return True

    if collection.find_one({"id": asset_price.id}, {"_id": 1}) is not None:
        logger.info(
            "Discarding older price observation for asset %s at %s",
            asset_price.id,
            asset_price.observed_at,
        )
        return False

    try:
        collection.insert_one({**doc, "created": created})
    except DuplicateKeyError:
        logger.info(
            "A concurrent price writer won the insert for asset %s",
            asset_price.id,
        )
        return False
    return True


def _current_price_after_rejected_write(asset_id: int) -> AssetPrice:
    current = db.asset_prices.get_one(id=asset_id)
    if current is None:
        raise PyMongoError(
            f"price write for asset {asset_id} lost a race but no winner exists",
        )
    return current


async def create_asset_prices_batch(
    asset_ids: list[int],
    current_round: int,
    algo_price_usd: float | None = None,
) -> list[AssetPrice]:
    """Create prices for multiple assets using Vestige batch API.

    LP token prices are handled by the background worker (lp_prices.py),
    not by this function.
    """
    from flex.providers.vestige import vestige_batch_prices

    if not asset_ids:
        return []

    vestige_prices = []
    batch_result = await vestige_batch_prices(asset_ids)
    for aid in asset_ids:
        price = batch_result.get(aid)
        if price is None:
            logger.warning(f"No Vestige price for asset {aid}")
            continue

        try:
            quote = validate_provider_quote(
                price,
                asset_id=aid,
                source=PriceSource.VESTIGE,
                fresh_for=_price_freshness_window(),
                observed_round=current_round,
            )
            asset_details = await get_asset_details(aid)
            asset_price = _asset_price_from_quote(
                quote,
                name=asset_details.name,
                current_round=current_round,
            )
            if not _upsert_asset_price(asset_price):
                asset_price = _current_price_after_rejected_write(aid)
        except (
            PriceRefreshError,
            AlgodHTTPError,
            IndexerHTTPError,
            PyMongoError,
        ) as exc:
            logger.warning("Skipping asset %s during batch refresh: %s", aid, exc)
            continue

        vestige_prices.append(asset_price)

    logger.info(f"Batch prices: {len(vestige_prices)}/{len(asset_ids)} created")
    return vestige_prices


async def create_asset_price(
    asset_id: int,
    current_round: int,
    algo_price_usd: float | None = None,
) -> AssetPrice:
    """Create a stored price only after the provider observation is validated."""

    quote = await fetch_vestige_price_quote(
        asset_id,
        fresh_for=_price_freshness_window(),
        observed_round=current_round,
    )
    asset_details = await get_asset_details(asset_id)
    logger.debug("Creating asset price %s = %s", asset_id, asset_details.name)
    asset_price = _asset_price_from_quote(
        quote,
        name=asset_details.name,
        current_round=current_round,
    )
    if not _upsert_asset_price(asset_price):
        return _current_price_after_rejected_write(asset_id)
    logger.info(
        "Asset Price %s (id=%s): usd=%s, algo=%s",
        asset_price.name,
        asset_price.id,
        asset_price.price_usd,
        asset_price.price_algo,
    )
    return asset_price


async def update_asset_price(
    asset_price: AssetPrice,
    current_round: int,
    algo_price_usd: float | None = None,
) -> AssetPrice:
    """Refresh an asset atomically; expected provider failures are typed and never persisted."""

    logger.debug("Updating Asset Price id=%s, algo_price=%s", asset_price.id, asset_price.price_algo)
    quote = await fetch_vestige_price_quote(
        asset_price.id,
        fresh_for=_price_freshness_window(),
        observed_round=current_round,
    )
    price_algo, price_usd = quote.to_legacy_floats()
    refreshed = replace(
        asset_price,
        price_algo=price_algo,
        price_usd=price_usd,
        last_update_round=quote.observed_round if quote.observed_round is not None else current_round,
        source=quote.source.value,
        observed_at=quote.observed_at,
    )
    if not _upsert_asset_price(refreshed):
        return _current_price_after_rejected_write(asset_price.id)
    logger.debug("Fresh Asset Price id=%s, algo_price=%s", refreshed.id, refreshed.price_algo)
    return refreshed


@cached(
    ttl=settings.asset_prices_ttl,
    namespace="asset_price",
    key_builder=build_key_str,
    skip_cache_func=_skip_asset_price_cache,
)
async def get_asset_price(asset_id: int) -> AssetPrice:
    return await get_asset_price_not_cached(asset_id)


async def get_asset_price_not_cached(asset_id: int) -> AssetPrice:
    asset_price = db.asset_prices.get_one(id=asset_id)

    if asset_price is None:
        current_round = await get_current_round()
        try:
            return await create_asset_price(asset_id, current_round)
        except PriceRefreshError as exc:
            raise PriceUnavailableError(
                f"no price is available for asset {asset_id}",
            ) from exc

    fresh = validated_stored_asset_price(
        asset_price,
        max_age=_price_freshness_window(),
    )
    if fresh is not None:
        return fresh

    current_round = await get_current_round()
    try:
        return await update_asset_price(asset_price, current_round)
    except PriceRefreshError as exc:
        fallback = validated_stored_asset_price(
            asset_price,
            max_age=_price_max_stale_window(),
        )
        if fallback is None:
            raise PriceUnavailableError(
                f"no valid price for asset {asset_id} exists inside the maximum stale window",
            ) from exc
        logger.warning(
            "Price refresh failed for asset %s; serving bounded-stale value: %s",
            asset_id,
            exc,
        )
        return fallback


async def get_all_asset_prices(current_time: datetime | None = None) -> list[AssetPriceInfo]:
    current_time = current_time or datetime.now(UTC)
    all_prices = db.asset_prices.get_all()
    max_age = _price_max_stale_window()
    return [
        asset_price.to_info(current_time)
        for asset_price in all_prices
        if validated_stored_asset_price(
            asset_price,
            max_age=max_age,
            now=current_time,
        )
        is not None
    ]


async def get_asset_prices_by_query(query_dict: dict, current_time: datetime | None = None) -> list[AssetPriceInfo]:
    current_time = current_time or datetime.now(UTC)

    matching_prices = db.asset_prices.get_many_by_query(query_dict)
    max_age = _price_max_stale_window()
    return [
        asset_price.to_info(current_time)
        for asset_price in matching_prices
        if validated_stored_asset_price(
            asset_price,
            max_age=max_age,
            now=current_time,
        )
        is not None
    ]


async def create_and_update_asset_prices() -> list[AssetPrice]:
    logger.info("Creating all asset prices.")

    all_assets = db.assets.get_all()
    asset_prices = []
    for asset in all_assets:
        try:
            asset_price = await get_asset_price_not_cached(asset.id)
            asset_prices.append(asset_price)
        except (PriceRefreshError, PriceUnavailableError) as exc:
            logger.warning("Could not refresh asset %s: %s", asset.id, exc)

    logger.info(f"{len(asset_prices)} asset prices created/updated.")
    return asset_prices
