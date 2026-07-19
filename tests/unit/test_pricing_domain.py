import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from algosdk.error import IndexerHTTPError
from pymongo.errors import DuplicateKeyError, PyMongoError

from flex.application.price_refresh import (
    PriceDataError,
    PriceRefreshError,
    validate_provider_quote,
)
from flex.data import asset_prices as asset_price_data
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import (
    MAX_OBSERVATION_CLOCK_SKEW,
    InvalidPriceError,
    PriceQuote,
    PriceSource,
    PricingError,
    calculate_lp_token_price_algo,
    is_observation_stale,
)
from flex.providers import vestige


def test_lp_price_keeps_exact_precision_above_float_integer_limit() -> None:
    exact_micros = 2**53 + 1

    result = calculate_lp_token_price_algo(
        asset1_price_algo=Decimal("1.23456789"),
        asset1_reserve_micros=exact_micros,
        asset1_decimals=0,
        total_lp_supply_micros=exact_micros + 2,
        pool_lp_balance_micros=2,
        lp_token_decimals=0,
    )

    assert result == Decimal("2.46913578")


def test_lp_price_accounts_for_asset_decimals_and_pool_owned_supply() -> None:
    result = calculate_lp_token_price_algo(
        asset1_price_algo="0.125",
        asset1_reserve_micros=12_345_678,
        asset1_decimals=6,
        total_lp_supply_micros=9_000_000_000,
        pool_lp_balance_micros=1_000_000_000,
        lp_token_decimals=8,
    )

    assert result == Decimal("0.03858024375")


def test_repeating_lp_ratio_is_rounded_to_quote_precision() -> None:
    result = calculate_lp_token_price_algo(
        asset1_price_algo=1,
        asset1_reserve_micros=1,
        asset1_decimals=0,
        total_lp_supply_micros=3,
        pool_lp_balance_micros=0,
        lp_token_decimals=0,
    )

    quote = PriceQuote.from_raw(
        asset_id=99,
        algo=result,
        usd=result,
        source=PriceSource.DERIVED_LP,
        stale_after=timedelta(minutes=5),
    )

    assert len(result.as_tuple().digits) == 34
    assert quote.algo == result


@pytest.mark.parametrize(
    ("price", "reserve", "total_supply", "pool_balance"),
    [
        (Decimal("NaN"), 1, 2, 0),
        (Decimal("Infinity"), 1, 2, 0),
        (Decimal("-1"), 1, 2, 0),
        (Decimal("1"), 0, 2, 0),
        (Decimal("1"), -1, 2, 0),
        (Decimal("1"), 1, 2, 2),
        (Decimal("1"), 1, 2, 3),
    ],
)
def test_lp_price_rejects_unsafe_inputs(
    price: Decimal,
    reserve: int,
    total_supply: int,
    pool_balance: int,
) -> None:
    with pytest.raises(PricingError):
        calculate_lp_token_price_algo(
            asset1_price_algo=price,
            asset1_reserve_micros=reserve,
            asset1_decimals=6,
            total_lp_supply_micros=total_supply,
            pool_lp_balance_micros=pool_balance,
            lp_token_decimals=6,
        )


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01"), Decimal("0"), True],
)
def test_price_quote_rejects_invalid_provider_values(value: Decimal | bool) -> None:
    with pytest.raises(InvalidPriceError):
        PriceQuote.from_raw(
            asset_id=1,
            algo=value,
            usd=Decimal("1"),
            source=PriceSource.VESTIGE,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            stale_after=timedelta(minutes=1),
        )


def test_price_quote_preserves_decimal_value_and_freshness_boundary() -> None:
    observed_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    quote = PriceQuote.from_raw(
        asset_id=42,
        algo="9007199254740993.0000001",
        usd="1.25",
        source=PriceSource.TINYMAN,
        observed_at=observed_at,
        observed_round=123,
        stale_after=timedelta(minutes=5),
    )

    assert quote.algo == Decimal("9007199254740993.0000001")
    assert quote.observed_at == observed_at
    assert quote.is_stale(now=datetime(2026, 1, 1, 12, 4, 59, 999999, tzinfo=UTC)) is False
    assert quote.is_stale(now=datetime(2026, 1, 1, 12, 5, tzinfo=UTC)) is True


def test_provider_boundary_rejects_misattributed_quote() -> None:
    quote = PriceQuote.from_raw(
        asset_id=42,
        algo="1",
        usd="0.25",
        source=PriceSource.TINYMAN,
        stale_after=timedelta(minutes=1),
    )

    with pytest.raises(PriceDataError, match="attributed to tinyman"):
        validate_provider_quote(
            quote,
            asset_id=42,
            source=PriceSource.VESTIGE,
            fresh_for=timedelta(minutes=1),
            observed_round=123,
        )


def test_provider_boundary_rejects_future_dated_quote() -> None:
    quote = PriceQuote.from_raw(
        asset_id=42,
        algo="1",
        usd="0.25",
        source=PriceSource.VESTIGE,
        observed_at=datetime.now(UTC) + MAX_OBSERVATION_CLOCK_SKEW + timedelta(seconds=1),
        stale_after=timedelta(minutes=1),
    )

    with pytest.raises(PriceDataError, match="too far in the future"):
        validate_provider_quote(
            quote,
            asset_id=42,
            source=PriceSource.VESTIGE,
            fresh_for=timedelta(minutes=1),
            observed_round=123,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_id": True},
        {"asset_id": "42"},
        {"source": "unknown-provider"},
        {"observed_at": "2026-01-01"},
        {"observed_round": True},
        {"stale_after": 60},
    ],
)
def test_price_quote_rejects_malformed_metadata(overrides: dict) -> None:
    values = {
        "asset_id": 42,
        "algo": "1",
        "usd": "0.25",
        "source": PriceSource.VESTIGE,
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "observed_round": 100,
        "stale_after": timedelta(minutes=1),
    }
    values.update(overrides)

    with pytest.raises(InvalidPriceError):
        PriceQuote.from_raw(**values)


def test_standalone_freshness_uses_the_same_inclusive_boundary() -> None:
    observed_at = datetime(2026, 1, 1, 12, tzinfo=UTC)

    assert (
        is_observation_stale(
            observed_at,
            fresh_for=timedelta(seconds=30),
            now=observed_at + timedelta(seconds=29),
        )
        is False
    )
    assert (
        is_observation_stale(
            observed_at,
            fresh_for=timedelta(seconds=30),
            now=observed_at + timedelta(seconds=30),
        )
        is True
    )


def test_future_observation_is_never_treated_as_fresh() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    observed_at = now + MAX_OBSERVATION_CLOCK_SKEW + timedelta(microseconds=1)
    quote = PriceQuote.from_raw(
        asset_id=42,
        algo="1",
        usd="0.25",
        source=PriceSource.VESTIGE,
        observed_at=observed_at,
        stale_after=timedelta(minutes=5),
    )

    assert (
        is_observation_stale(
            observed_at,
            fresh_for=timedelta(minutes=5),
            now=now,
        )
        is True
    )
    assert quote.is_stale(now=now) is True


def _stored_asset_price(
    *,
    updated: datetime,
    observed_at: datetime | None = None,
) -> AssetPrice:
    return AssetPrice(
        id=42,
        name="USDC",
        price_algo=0.25,
        price_usd=1.0,
        last_update_round=100,
        source=None,
        observed_at=observed_at,
        created=updated - timedelta(days=1),
        updated=updated,
    )


def test_legacy_asset_price_hydrates_without_provenance_and_keeps_api_shape() -> None:
    updated = datetime(2026, 1, 1, 12, tzinfo=UTC)
    legacy_document = {
        "id": 42,
        "name": "USDC",
        "price_algo": 0.25,
        "price_usd": 1.0,
        "last_update_round": 100,
        "created": updated - timedelta(days=1),
        "updated": updated,
    }

    stored = AssetPrice.from_dict(legacy_document)

    assert stored is not None
    assert stored.source is None
    assert stored.observed_at is None
    assert stored.to_info(updated + timedelta(seconds=45)).to_dict() == {
        "asset_id": 42,
        "asset_name": "USDC",
        "price_usd": 1.0,
        "price_algo": 0.25,
        "last_update_round": 100,
        "seconds_since_update": 45,
    }


def test_asset_price_freshness_prefers_observation_then_falls_back_to_updated() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    fresh_for = timedelta(seconds=30)
    stale_observation = _stored_asset_price(
        updated=now,
        observed_at=now - timedelta(seconds=31),
    )
    legacy_fresh = _stored_asset_price(updated=now - timedelta(seconds=29))
    legacy_at_boundary = _stored_asset_price(updated=now - timedelta(seconds=30))

    assert asset_price_data.is_asset_price_stale(stale_observation, now=now, fresh_for=fresh_for) is True
    assert asset_price_data.is_asset_price_stale(legacy_fresh, now=now, fresh_for=fresh_for) is False
    assert asset_price_data.is_asset_price_stale(legacy_at_boundary, now=now, fresh_for=fresh_for) is True


def test_failed_asset_price_refresh_does_not_write_or_mutate(monkeypatch) -> None:
    updated = datetime(2026, 1, 1, 12, tzinfo=UTC)
    stored = _stored_asset_price(updated=updated)
    original = deepcopy(stored)
    update_one = Mock()
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=SimpleNamespace(update_one=update_one),
            ),
        ),
    )

    async def fail_refresh(*args, **kwargs) -> PriceQuote:
        raise PriceRefreshError(stored.id, PriceSource.VESTIGE, "provider unavailable")

    monkeypatch.setattr(asset_price_data, "fetch_vestige_price_quote", fail_refresh)

    with pytest.raises(PriceRefreshError, match="provider unavailable"):
        asyncio.run(asset_price_data.update_asset_price(stored, current_round=200))

    assert stored == original
    update_one.assert_not_called()


def test_successful_asset_price_refresh_persists_provenance_without_mutating_input(monkeypatch) -> None:
    updated = datetime(2026, 1, 1, 12, tzinfo=UTC)
    observed_at = updated + timedelta(minutes=1)
    stored = _stored_asset_price(updated=updated)
    original = deepcopy(stored)
    quote = PriceQuote.from_raw(
        asset_id=stored.id,
        algo="0.125",
        usd="0.99",
        source=PriceSource.VESTIGE,
        observed_at=observed_at,
        observed_round=777,
        stale_after=timedelta(minutes=5),
    )
    update_one = Mock(return_value=SimpleNamespace(matched_count=1))
    collection = SimpleNamespace(
        update_one=update_one,
        find_one=Mock(),
        insert_one=Mock(),
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            ),
        ),
    )

    async def fetch_quote(*args, **kwargs) -> PriceQuote:
        return quote

    monkeypatch.setattr(asset_price_data, "fetch_vestige_price_quote", fetch_quote)

    refreshed = asyncio.run(asset_price_data.update_asset_price(stored, current_round=888))

    assert stored == original
    assert refreshed is not stored
    assert refreshed.price_algo == 0.125
    assert refreshed.price_usd == 0.99
    assert refreshed.last_update_round == 777
    assert refreshed.source == PriceSource.VESTIGE.value
    assert refreshed.observed_at == observed_at

    update_one.assert_called_once()
    selector, update = update_one.call_args.args
    assert selector == AssetPrice.encode_query(
        {
            "id": stored.id,
            "$or": [
                {"observed_at": {"$exists": False}},
                {"observed_at": None},
                {"observed_at": {"$lte": observed_at}},
                {
                    "observed_at": {
                        "$gt": refreshed.updated + MAX_OBSERVATION_CLOCK_SKEW,
                    }
                },
            ],
        }
    )
    assert update["$set"]["source"] == PriceSource.VESTIGE.value
    assert update["$set"]["observed_at"] == observed_at
    assert update_one.call_args.kwargs == {"upsert": False}
    collection.find_one.assert_not_called()
    collection.insert_one.assert_not_called()


def test_future_dated_asset_price_is_rejected_before_database_io(
    monkeypatch,
) -> None:
    future = datetime.now(UTC) + MAX_OBSERVATION_CLOCK_SKEW + timedelta(seconds=1)
    price = _stored_asset_price(
        updated=future,
        observed_at=future,
    )
    collection = SimpleNamespace(
        update_one=Mock(),
        find_one=Mock(),
        insert_one=Mock(),
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            ),
        ),
    )

    with pytest.raises(InvalidPriceError, match="too far in the future"):
        asset_price_data._upsert_asset_price(price)

    collection.update_one.assert_not_called()
    collection.find_one.assert_not_called()
    collection.insert_one.assert_not_called()


def test_older_asset_price_observation_cannot_replace_newer_record(
    monkeypatch,
) -> None:
    older_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    older = _stored_asset_price(
        updated=older_time,
        observed_at=older_time,
    )
    collection = SimpleNamespace(
        update_one=Mock(return_value=SimpleNamespace(matched_count=0)),
        find_one=Mock(return_value={"_id": "newer-record"}),
        insert_one=Mock(),
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            ),
        ),
    )

    persisted = asset_price_data._upsert_asset_price(older)

    assert persisted is False
    collection.find_one.assert_called_once_with(
        AssetPrice.encode_query({"id": older.id}),
        {"_id": 1},
    )
    collection.insert_one.assert_not_called()


def test_newer_initial_price_retries_after_concurrent_older_insert(
    monkeypatch,
) -> None:
    observed_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    newer = _stored_asset_price(
        updated=observed_at,
        observed_at=observed_at,
    )
    collection = SimpleNamespace(
        update_one=Mock(
            side_effect=[
                SimpleNamespace(matched_count=0),
                SimpleNamespace(matched_count=1),
            ]
        ),
        find_one=Mock(return_value=None),
        insert_one=Mock(side_effect=DuplicateKeyError("concurrent insert")),
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            ),
        ),
    )

    persisted = asset_price_data._upsert_asset_price(newer)

    assert persisted is True
    assert collection.update_one.call_count == 2
    first_selector, first_update = collection.update_one.call_args_list[0].args
    retry_selector, retry_update = collection.update_one.call_args_list[1].args
    assert retry_selector == first_selector
    assert retry_update == {"$set": first_update["$set"]}
    assert collection.update_one.call_args_list[1].kwargs == {"upsert": False}


def test_batch_refresh_isolates_expected_asset_metadata_failure(monkeypatch) -> None:
    async def batch_prices(asset_ids: list[int]) -> dict[int, vestige.Price]:
        return {asset_id: vestige.Price(algo=0.25, usd=1.0) for asset_id in asset_ids}

    async def asset_details(asset_id: int):
        if asset_id == 1:
            raise IndexerHTTPError("asset missing")
        return SimpleNamespace(name=f"ASSET-{asset_id}")

    persisted: list[AssetPrice] = []

    def persist(asset_price: AssetPrice) -> bool:
        persisted.append(asset_price)
        return True

    monkeypatch.setattr(vestige, "vestige_batch_prices", batch_prices)
    monkeypatch.setattr(asset_price_data, "get_asset_details", asset_details)
    monkeypatch.setattr(asset_price_data, "_upsert_asset_price", persist)

    result = asyncio.run(
        asset_price_data.create_asset_prices_batch(
            [1, 2],
            current_round=777,
        ),
    )

    assert [price.id for price in result] == [2]
    assert [price.id for price in persisted] == [2]


def test_batch_refresh_isolates_expected_item_persistence_failure(monkeypatch) -> None:
    async def batch_prices(asset_ids: list[int]) -> dict[int, vestige.Price]:
        return {asset_id: vestige.Price(algo=0.25, usd=1.0) for asset_id in asset_ids}

    async def asset_details(asset_id: int):
        return SimpleNamespace(name=f"ASSET-{asset_id}")

    persisted: list[int] = []

    def upsert(asset_price: AssetPrice) -> bool:
        if asset_price.id == 1:
            raise PyMongoError("temporary write failure")
        persisted.append(asset_price.id)
        return True

    monkeypatch.setattr(vestige, "vestige_batch_prices", batch_prices)
    monkeypatch.setattr(asset_price_data, "get_asset_details", asset_details)
    monkeypatch.setattr(asset_price_data, "_upsert_asset_price", upsert)

    result = asyncio.run(
        asset_price_data.create_asset_prices_batch(
            [1, 2],
            current_round=777,
        ),
    )

    assert [price.id for price in result] == [2]
    assert persisted == [2]


def test_batch_refresh_returns_concurrent_newer_price_when_write_loses(
    monkeypatch,
) -> None:
    async def batch_prices(asset_ids: list[int]) -> dict[int, vestige.Price]:
        return {42: vestige.Price(algo=0.25, usd=1.0)}

    async def asset_details(asset_id: int):
        return SimpleNamespace(name="CANDIDATE")

    winner = _stored_asset_price(
        updated=datetime.now(UTC),
        observed_at=datetime.now(UTC),
    )
    winner.name = "WINNER"
    monkeypatch.setattr(vestige, "vestige_batch_prices", batch_prices)
    monkeypatch.setattr(asset_price_data, "get_asset_details", asset_details)
    monkeypatch.setattr(
        asset_price_data,
        "_upsert_asset_price",
        lambda asset_price: False,
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                get_one=lambda **kwargs: winner,
            ),
        ),
    )

    result = asyncio.run(
        asset_price_data.create_asset_prices_batch(
            [42],
            current_round=777,
        ),
    )

    assert result == [winner]
