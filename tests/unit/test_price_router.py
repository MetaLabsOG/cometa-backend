import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from env import settings
from flex.domain.pricing import PriceSource, PriceUnavailableError
from flex.meta_error import MetaError
from flex.providers import price_router, vestige
from flex.providers.vestige import Price


def _record(
    *,
    age_seconds: int,
    algo: float = 2.0,
    usd: float = 0.5,
    tinyman_algo_pool_id: int | None = None,
    source: str = PriceSource.VESTIGE.value,
):
    observed_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return SimpleNamespace(
        id=42,
        price_algo=algo,
        price_usd=usd,
        source=source,
        tinyman_algo_pool_id=tinyman_algo_pool_id,
        observed_at=observed_at,
        updated=observed_at,
    )


def _database(monkeypatch, record) -> None:
    monkeypatch.setattr(
        price_router,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                get_one=lambda **kwargs: record,
            ),
        ),
    )


async def _provider_failure(*args):
    raise httpx.ConnectError("provider unavailable")


def test_fresh_database_price_short_circuits_providers(monkeypatch) -> None:
    _database(monkeypatch, _record(age_seconds=0))

    async def unexpected_provider_call(*args):
        raise AssertionError("fresh database price should have short-circuited")

    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", unexpected_provider_call)
    monkeypatch.setattr(
        price_router,
        "_asset_price_from_tinyman",
        unexpected_provider_call,
    )

    result = asyncio.run(price_router.get_asset_price(42))

    assert result == Price(algo=2.0, usd=0.5)


def test_invalid_provider_data_falls_through_to_next_provider(monkeypatch) -> None:
    _database(monkeypatch, None)

    async def invalid_vestige_price(asset_id: int) -> Price:
        return Price(algo=float("nan"), usd=1.0)

    async def valid_tinyman_price(asset_id: int) -> Price:
        return Price(algo=3.0, usd=0.75)

    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", invalid_vestige_price)
    monkeypatch.setattr(price_router, "_asset_price_from_tinyman", valid_tinyman_price)

    result = asyncio.run(price_router.get_asset_price(42))

    assert result == Price(algo=3.0, usd=0.75)


def test_invalid_vestige_json_falls_through_to_next_provider(monkeypatch) -> None:
    _database(monkeypatch, None)

    async def malformed_vestige_response(asset_id: int) -> Price:
        raise MetaError("Invalid Vestige JSON response")

    async def valid_tinyman_price(asset_id: int) -> Price:
        return Price(algo=3.0, usd=0.75)

    monkeypatch.setattr(
        vestige,
        "vestige_full_asset_price_not_cached",
        malformed_vestige_response,
    )
    monkeypatch.setattr(
        price_router,
        "_asset_price_from_tinyman",
        valid_tinyman_price,
    )

    result = asyncio.run(price_router.get_asset_price(42))

    assert result == Price(algo=3.0, usd=0.75)


def test_fresh_database_price_with_zero_algo_leg_does_not_short_circuit(monkeypatch) -> None:
    _database(monkeypatch, _record(age_seconds=0, algo=0.0, usd=1.0))

    async def valid_vestige_price(asset_id: int) -> Price:
        return Price(algo=3.0, usd=0.75)

    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", valid_vestige_price)

    result = asyncio.run(price_router.get_asset_price(42))

    assert result == Price(algo=3.0, usd=0.75)


def test_provider_outage_uses_only_bounded_stale_database_price(monkeypatch) -> None:
    stale_age = settings.asset_prices_ttl + 1
    assert stale_age < settings.asset_prices_max_stale
    _database(monkeypatch, _record(age_seconds=stale_age))
    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", _provider_failure)
    monkeypatch.setattr(price_router, "_asset_price_from_tinyman", _provider_failure)

    result = asyncio.run(price_router.get_asset_price(42))

    assert result == Price(algo=2.0, usd=0.5)


def test_provider_outage_never_uses_legacy_raw_lp_projection(monkeypatch) -> None:
    _database(
        monkeypatch,
        _record(age_seconds=0, tinyman_algo_pool_id=999),
    )
    monkeypatch.setattr(
        vestige,
        "vestige_full_asset_price_not_cached",
        _provider_failure,
    )
    monkeypatch.setattr(
        price_router,
        "_asset_price_from_tinyman",
        _provider_failure,
    )

    with pytest.raises(PriceUnavailableError, match="no acceptable fallback"):
        asyncio.run(price_router.get_asset_price(42))


def test_provider_outage_never_uses_derived_lp_source_without_pool_marker(
    monkeypatch,
) -> None:
    _database(
        monkeypatch,
        _record(
            age_seconds=0,
            source=PriceSource.DERIVED_LP.value,
        ),
    )
    monkeypatch.setattr(
        vestige,
        "vestige_full_asset_price_not_cached",
        _provider_failure,
    )
    monkeypatch.setattr(
        price_router,
        "_asset_price_from_tinyman",
        _provider_failure,
    )

    with pytest.raises(PriceUnavailableError, match="no acceptable fallback"):
        asyncio.run(price_router.get_asset_price(42))


def test_bounded_stale_quote_preserves_original_provenance(monkeypatch) -> None:
    stale_age = settings.asset_prices_ttl + 1
    record = _record(age_seconds=stale_age)
    _database(monkeypatch, record)
    monkeypatch.setattr(
        vestige,
        "vestige_full_asset_price_not_cached",
        _provider_failure,
    )
    monkeypatch.setattr(price_router, "_asset_price_from_tinyman", _provider_failure)

    quote = asyncio.run(price_router.get_asset_price_quote(42))

    assert quote.source is PriceSource.VESTIGE
    assert quote.observed_at == record.observed_at
    assert quote.to_legacy_floats() == (2.0, 0.5)


def test_price_older_than_max_stale_is_rejected(monkeypatch) -> None:
    _database(
        monkeypatch,
        _record(age_seconds=settings.asset_prices_max_stale + 1),
    )
    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", _provider_failure)
    monkeypatch.setattr(price_router, "_asset_price_from_tinyman", _provider_failure)

    with pytest.raises(PriceUnavailableError, match="no acceptable fallback"):
        asyncio.run(price_router.get_asset_price(42))


def test_unexpected_programming_errors_are_not_swallowed(monkeypatch) -> None:
    _database(monkeypatch, None)

    async def broken_provider(asset_id: int) -> Price:
        raise AssertionError("provider adapter bug")

    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", broken_provider)

    with pytest.raises(AssertionError, match="adapter bug"):
        asyncio.run(price_router.get_asset_price(42))


def test_algo_transport_error_is_normalized_for_bounded_stale_fallback(
    monkeypatch,
) -> None:
    from flex.application import price_refresh

    async def failed_algo_price(asset_id: int) -> float:
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(vestige, "vestige_full_asset_price_not_cached", failed_algo_price)

    with pytest.raises(
        price_refresh.PriceProviderUnavailableError,
        match="provider unavailable",
    ):
        asyncio.run(
            price_refresh.fetch_vestige_price_quote(
                0,
                fresh_for=timedelta(seconds=30),
                observed_round=123,
            ),
        )
