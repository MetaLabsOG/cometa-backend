import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from env import settings
from flex.data import asset_prices
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import (
    PriceQuote,
    PriceSource,
    PriceUnavailableError,
    PricingError,
)


def _stored_price(
    *,
    age_seconds: int,
    price_algo: float = 2.0,
    price_usd: float = 0.5,
    tinyman_algo_pool_id: int | None = None,
    source: str = "vestige",
) -> AssetPrice:
    observed_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return AssetPrice(
        id=42,
        name="TEST",
        price_algo=price_algo,
        price_usd=price_usd,
        last_update_round=123,
        tinyman_algo_pool_id=tinyman_algo_pool_id,
        source=source,
        observed_at=observed_at,
        created=observed_at,
        updated=observed_at,
    )


def _database(monkeypatch, stored: AssetPrice | None) -> None:
    async def current_round() -> int:
        return 456

    monkeypatch.setattr(
        asset_prices,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(get_one=lambda **kwargs: stored),
        ),
    )
    monkeypatch.setattr(asset_prices, "get_current_round", current_round)


async def _failed_refresh(*args, **kwargs):
    from flex.application.price_refresh import PriceRefreshError
    from flex.domain.pricing import PriceSource

    raise PriceRefreshError(42, PriceSource.VESTIGE, "provider unavailable")


def test_refresh_failure_serves_only_bounded_stale_price(monkeypatch) -> None:
    stored = _stored_price(age_seconds=settings.asset_prices_ttl + 1)
    _database(monkeypatch, stored)
    monkeypatch.setattr(asset_prices, "update_asset_price", _failed_refresh)

    result = asyncio.run(asset_prices.get_asset_price_not_cached(42))

    assert result is stored


def test_initial_provider_outage_is_normalized_to_unavailable(monkeypatch) -> None:
    _database(monkeypatch, None)
    monkeypatch.setattr(asset_prices, "create_asset_price", _failed_refresh)

    with pytest.raises(PriceUnavailableError, match="no price is available"):
        asyncio.run(asset_prices.get_asset_price_not_cached(42))


def test_refresh_failure_rejects_price_older_than_max_stale(monkeypatch) -> None:
    stored = _stored_price(age_seconds=settings.asset_prices_max_stale + 1)
    _database(monkeypatch, stored)
    monkeypatch.setattr(asset_prices, "update_asset_price", _failed_refresh)

    with pytest.raises(PriceUnavailableError, match="maximum stale window"):
        asyncio.run(asset_prices.get_asset_price_not_cached(42))


def test_refresh_failure_never_serves_legacy_raw_lp_projection(monkeypatch) -> None:
    stored = _stored_price(age_seconds=0, tinyman_algo_pool_id=999)
    _database(monkeypatch, stored)
    monkeypatch.setattr(asset_prices, "update_asset_price", _failed_refresh)

    with pytest.raises(PriceUnavailableError, match="maximum stale window"):
        asyncio.run(asset_prices.get_asset_price_not_cached(42))


def test_refresh_failure_never_serves_derived_lp_source_without_pool_marker(
    monkeypatch,
) -> None:
    stored = _stored_price(age_seconds=0, source=PriceSource.DERIVED_LP.value)
    _database(monkeypatch, stored)
    monkeypatch.setattr(asset_prices, "update_asset_price", _failed_refresh)

    with pytest.raises(PriceUnavailableError, match="maximum stale window"):
        asyncio.run(asset_prices.get_asset_price_not_cached(42))


def test_provider_refresh_removes_legacy_raw_lp_provenance(monkeypatch) -> None:
    stored = _stored_price(age_seconds=0, tinyman_algo_pool_id=999)
    observed_at = datetime.now(UTC)
    quote = PriceQuote.from_raw(
        asset_id=42,
        algo="3",
        usd="0.75",
        source=PriceSource.VESTIGE,
        observed_at=observed_at,
        observed_round=456,
        stale_after=timedelta(seconds=settings.asset_prices_ttl),
    )
    persisted = []

    async def fetch_quote(*args, **kwargs) -> PriceQuote:
        return quote

    monkeypatch.setattr(asset_prices, "fetch_vestige_price_quote", fetch_quote)
    monkeypatch.setattr(
        asset_prices,
        "_upsert_asset_price",
        lambda price: persisted.append(price) is None,
    )

    result = asyncio.run(asset_prices.update_asset_price(stored, current_round=456))

    assert result.tinyman_algo_pool_id is None
    assert result.source == PriceSource.VESTIGE.value
    assert result.observed_at == observed_at
    assert persisted == [result]


def test_legacy_raw_lp_projection_cannot_cross_persistence_boundary() -> None:
    stored = _stored_price(age_seconds=0, tinyman_algo_pool_id=999)

    with pytest.raises(PricingError, match="projections are retired"):
        asset_prices._upsert_asset_price(stored)


def test_derived_lp_source_without_pool_marker_cannot_be_persisted() -> None:
    stored = _stored_price(
        age_seconds=0,
        source=PriceSource.DERIVED_LP.value,
    )

    with pytest.raises(PricingError, match="projections are retired"):
        asset_prices._upsert_asset_price(stored)


def test_invalid_fresh_database_value_is_refreshed(monkeypatch) -> None:
    stored = _stored_price(age_seconds=0, price_algo=float("nan"))
    refreshed = _stored_price(age_seconds=0, price_algo=3.0, price_usd=0.75)
    _database(monkeypatch, stored)

    async def successful_refresh(*args, **kwargs) -> AssetPrice:
        return refreshed

    monkeypatch.setattr(
        asset_prices,
        "update_asset_price",
        successful_refresh,
    )

    result = asyncio.run(asset_prices.get_asset_price_not_cached(42))

    assert result is refreshed


def test_list_reads_filter_invalid_and_expired_prices(monkeypatch) -> None:
    valid = _stored_price(age_seconds=0)
    invalid = _stored_price(age_seconds=0, price_usd=0)
    invalid.id = 43
    expired = _stored_price(
        age_seconds=settings.asset_prices_max_stale + 1,
    )
    expired.id = 44
    legacy = _stored_price(
        age_seconds=0,
        tinyman_algo_pool_id=999,
    )
    legacy.id = 45
    derived = _stored_price(
        age_seconds=0,
        source=PriceSource.DERIVED_LP.value,
    )
    derived.id = 46
    monkeypatch.setattr(
        asset_prices,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                get_all=lambda: [valid, invalid, expired, legacy, derived],
            ),
        ),
    )

    result = asyncio.run(asset_prices.get_all_asset_prices())

    assert [price.asset_id for price in result] == [42]


def test_cache_policy_cannot_extend_price_beyond_max_stale() -> None:
    fresh = _stored_price(age_seconds=0)
    near_expiry = _stored_price(
        age_seconds=(settings.asset_prices_max_stale - settings.asset_prices_ttl + 1),
    )

    assert asset_prices._skip_asset_price_cache(fresh) is False
    assert asset_prices._skip_asset_price_cache(near_expiry) is True
