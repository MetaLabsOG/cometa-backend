"""Application boundary for turning provider responses into safe price quotes."""

from dataclasses import replace
from datetime import timedelta
from typing import Protocol

import httpx

from flex.domain.pricing import (
    DecimalInput,
    PriceQuote,
    PriceSource,
    PricingError,
    validate_observation_timestamp,
)
from flex.meta_error import MetaError
from flex.providers import vestige


class PriceValues(Protocol):
    """Minimal compatibility contract implemented by legacy provider prices."""

    @property
    def algo(self) -> DecimalInput: ...

    @property
    def usd(self) -> DecimalInput: ...


class PriceRefreshError(RuntimeError):
    """An expected provider or quote-validation failure during a refresh."""

    def __init__(self, asset_id: int, provider: PriceSource, message: str) -> None:
        self.asset_id = asset_id
        self.provider = provider
        super().__init__(f"{provider.value} price refresh failed for asset {asset_id}: {message}")


class PriceProviderUnavailableError(PriceRefreshError):
    """A retryable transport, throttling, or upstream availability failure."""


class PriceDataError(PriceRefreshError):
    """A non-retryable malformed or unusable provider observation."""


def validate_provider_quote(
    price: PriceQuote | PriceValues,
    *,
    asset_id: int,
    source: PriceSource,
    fresh_for: timedelta,
    observed_round: int | None,
) -> PriceQuote:
    """Validate a provider value before it can cross the persistence boundary."""

    try:
        if isinstance(price, PriceQuote):
            if price.asset_id != asset_id:
                raise PriceDataError(
                    asset_id,
                    source,
                    f"provider returned quote for asset {price.asset_id}",
                )
            if price.source is not source:
                raise PriceDataError(
                    asset_id,
                    source,
                    f"provider returned quote attributed to {price.source.value}",
                )
            quote = (
                replace(price, observed_round=observed_round)
                if price.observed_round is None and observed_round is not None
                else price
            )
        else:
            quote = PriceQuote.from_raw(
                asset_id=asset_id,
                algo=price.algo,
                usd=price.usd,
                source=source,
                stale_after=fresh_for,
                observed_round=observed_round,
            )
        validate_observation_timestamp(quote.observed_at)
        quote.to_legacy_floats()
        return quote
    except PriceRefreshError:
        raise
    except PricingError as exc:
        raise PriceDataError(asset_id, source, str(exc)) from exc


async def fetch_vestige_price_quote(
    asset_id: int,
    *,
    fresh_for: timedelta,
    observed_round: int | None,
) -> PriceQuote:
    """Fetch and validate a Vestige quote, wrapping only expected failures."""

    try:
        price = await vestige.vestige_full_asset_price_not_cached(asset_id)
    except (httpx.HTTPError, vestige.VestigeUnavailableError) as exc:
        raise PriceProviderUnavailableError(
            asset_id,
            PriceSource.VESTIGE,
            str(exc),
        ) from exc
    except (MetaError, PricingError) as exc:
        raise PriceDataError(asset_id, PriceSource.VESTIGE, str(exc)) from exc

    return validate_provider_quote(
        price,
        asset_id=asset_id,
        source=PriceSource.VESTIGE,
        fresh_for=fresh_for,
        observed_round=observed_round,
    )
