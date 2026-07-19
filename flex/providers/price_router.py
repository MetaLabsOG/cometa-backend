"""Validated price routing with fresh and bounded-stale fallbacks."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from env import settings
from flex import db
from flex.data.asset_prices import is_unverified_legacy_lp_price
from flex.domain.pricing import (
    DecimalInput,
    PriceQuote,
    PriceSource,
    PriceUnavailableError,
    PricingError,
    is_observation_stale,
)
from flex.meta_error import MetaError
from flex.providers.vestige import Price, VestigeUnavailableError

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None

TINYMAN_ANALYTICS_BASE = "https://mainnet.analytics.tinyman.org/api/v1"
COINGECKO_ALGO_URL = "https://api.coingecko.com/api/v3/simple/price?ids=algorand&vs_currencies=usd"
_EXPECTED_PROVIDER_ERRORS = (
    httpx.HTTPError,
    MetaError,
    VestigeUnavailableError,
    PricingError,
)


class ProviderPayloadError(PricingError):
    """A provider response did not match its documented schema."""


class _StoredPrice(Protocol):
    price_algo: float
    price_usd: float
    source: str | None
    observed_at: datetime | None
    updated: datetime


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def _algo_price_from_coingecko() -> float:
    """Fetch ALGO/USD price from CoinGecko free API."""
    client = _get_client()
    response = await client.get(COINGECKO_ALGO_URL)
    response.raise_for_status()
    try:
        data = response.json()
        return float(data["algorand"]["usd"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProviderPayloadError("CoinGecko returned an invalid ALGO price payload") from exc


async def _algo_price_from_tinyman() -> float:
    """Fetch ALGO price from Tinyman Analytics (asset 0)."""
    client = _get_client()
    url = f"{TINYMAN_ANALYTICS_BASE}/assets/0/"
    response = await client.get(url)
    response.raise_for_status()
    try:
        data = response.json()
        return float(data["price_in_usd"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProviderPayloadError("Tinyman returned an invalid ALGO price payload") from exc


async def _asset_price_from_tinyman(asset_id: int) -> Price:
    """Fetch asset price from Tinyman Analytics."""
    client = _get_client()
    url = f"{TINYMAN_ANALYTICS_BASE}/assets/{asset_id}/"
    response = await client.get(url)
    response.raise_for_status()
    try:
        data = response.json()
        price_algo = float(data["price_in_algo"])
        price_usd = float(data["price_in_usd"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProviderPayloadError(
            f"Tinyman returned an invalid price payload for asset {asset_id}",
        ) from exc
    return Price(algo=price_algo, usd=price_usd)


def _validated_quote(
    *,
    asset_id: int,
    price: Price,
    source: PriceSource,
    observed_at: datetime,
) -> PriceQuote:
    return PriceQuote.from_raw(
        asset_id=asset_id,
        algo=price.algo,
        usd=price.usd,
        source=source,
        observed_at=observed_at,
        stale_after=timedelta(seconds=settings.asset_prices_ttl),
    )


def _validated_algo_quote(
    *,
    value: DecimalInput,
    source: PriceSource,
    observed_at: datetime,
) -> PriceQuote:
    return PriceQuote.from_raw(
        asset_id=0,
        algo=1,
        usd=value,
        source=source,
        observed_at=observed_at,
        stale_after=timedelta(seconds=settings.asset_prices_ttl),
    )


def _legacy_price(quote: PriceQuote) -> Price:
    algo, usd = quote.to_legacy_floats()
    return Price(algo=algo, usd=usd)


def _record_observed_at(record: _StoredPrice) -> datetime:
    observed_at = getattr(record, "observed_at", None)
    if isinstance(observed_at, datetime):
        return observed_at
    updated = getattr(record, "updated", None)
    if not isinstance(updated, datetime):
        raise PricingError("stored price has no observation timestamp")
    return updated


def _record_source(record: _StoredPrice) -> PriceSource:
    raw_source = getattr(record, "source", None)
    if raw_source is None:
        return PriceSource.DATABASE
    try:
        return PriceSource(raw_source)
    except (TypeError, ValueError):
        logger.warning("Stored price has unknown source %r; attributing it to the database", raw_source)
        return PriceSource.DATABASE


def _stored_quote(
    record: _StoredPrice | None,
    *,
    asset_id: int,
    now: datetime,
    max_age: timedelta,
) -> PriceQuote | None:
    if record is None or is_unverified_legacy_lp_price(record):
        if record is not None:
            logger.warning(
                "Ignoring retired raw-reserve LP projection for asset %s",
                asset_id,
            )
        return None
    try:
        observed_at = _record_observed_at(record)
        if is_observation_stale(observed_at, fresh_for=max_age, now=now):
            return None
        return PriceQuote.from_raw(
            asset_id=asset_id,
            algo=record.price_algo,
            usd=record.price_usd,
            source=_record_source(record),
            observed_at=observed_at,
            stale_after=max_age,
        )
    except (AttributeError, PricingError, TypeError, ValueError) as exc:
        logger.warning("Ignoring invalid stored price for asset %s: %s", asset_id, exc)
        return None


async def get_algo_price_quote() -> PriceQuote:
    """Return ALGO/USD with source and observation time intact."""
    from flex.providers.vestige import get_algo_price_usd_not_cached as vestige_algo_price

    now = datetime.now(UTC)
    providers = (
        ("Vestige", PriceSource.VESTIGE, vestige_algo_price),
        ("Tinyman", PriceSource.TINYMAN, _algo_price_from_tinyman),
        ("CoinGecko", PriceSource.COINGECKO, _algo_price_from_coingecko),
    )
    for name, source, provider in providers:
        try:
            value = await provider()
            return _validated_algo_quote(
                value=value,
                source=source,
                observed_at=datetime.now(UTC),
            )
        except _EXPECTED_PROVIDER_ERRORS as exc:
            logger.warning("%s ALGO price failed: %s", name, exc)

    algo_record = db.asset_prices.get_one(id=0)
    stored = _stored_quote(
        algo_record,
        asset_id=0,
        now=now,
        max_age=timedelta(seconds=settings.asset_prices_max_stale),
    )
    if stored is not None:
        logger.warning("Using bounded-stale ALGO price from the database")
        return stored

    raise PriceUnavailableError(
        "all ALGO price providers failed and no acceptable database fallback exists",
    )


async def get_algo_price_usd() -> float:
    """Compatibility wrapper returning only the ALGO/USD numeric value."""

    return _legacy_price(await get_algo_price_quote()).usd


async def get_asset_price_quote(asset_id: int) -> PriceQuote:
    """Return an asset quote without discarding provenance or freshness."""
    if asset_id == 0:
        return await get_algo_price_quote()

    now = datetime.now(UTC)
    record = db.asset_prices.get_one(id=asset_id)
    fresh = _stored_quote(
        record,
        asset_id=asset_id,
        now=now,
        max_age=timedelta(seconds=settings.asset_prices_ttl),
    )
    if fresh is not None:
        return fresh

    from flex.providers.vestige import vestige_full_asset_price_not_cached

    providers = (
        ("Vestige", PriceSource.VESTIGE, vestige_full_asset_price_not_cached),
        ("Tinyman", PriceSource.TINYMAN, _asset_price_from_tinyman),
    )
    for name, source, provider in providers:
        try:
            price = await provider(asset_id)
            return _validated_quote(
                asset_id=asset_id,
                price=price,
                source=source,
                observed_at=datetime.now(UTC),
            )
        except _EXPECTED_PROVIDER_ERRORS as exc:
            logger.warning("%s price failed for asset %s: %s", name, asset_id, exc)

    stale = _stored_quote(
        record,
        asset_id=asset_id,
        now=now,
        max_age=timedelta(seconds=settings.asset_prices_max_stale),
    )
    if stale is not None:
        logger.warning("Using bounded-stale database price for asset %s", asset_id)
        return stale

    raise PriceUnavailableError(
        f"all price providers failed for asset {asset_id} and no acceptable fallback exists",
    )


async def get_asset_price(asset_id: int) -> Price:
    """Compatibility wrapper returning the legacy two-float price shape."""

    return _legacy_price(await get_asset_price_quote(asset_id))
