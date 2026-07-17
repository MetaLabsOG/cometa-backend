import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from env import settings
from flex.data import asset_prices
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import PriceUnavailableError


def _stored_price(
    *,
    age_seconds: int,
    price_algo: float = 2.0,
    price_usd: float = 0.5,
) -> AssetPrice:
    observed_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return AssetPrice(
        id=42,
        name="TEST",
        price_algo=price_algo,
        price_usd=price_usd,
        last_update_round=123,
        source="vestige",
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
    monkeypatch.setattr(
        asset_prices,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                get_all=lambda: [valid, invalid, expired],
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
