import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from flex import api
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import PriceUnavailableError


def _lp_price(token_id: int, *, age_seconds: int = 0) -> AssetPrice:
    observed_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return AssetPrice(
        id=token_id,
        name=f"LP-{token_id}",
        price_algo=1.25 if token_id == 8 else 2.5,
        price_usd=0.42 if token_id == 8 else 0.84,
        last_update_round=123,
        source="derived_lp",
        observed_at=observed_at,
        created=observed_at,
        updated=observed_at,
    )


def test_lp_request_requires_exactly_one_selector() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        api.LpStatePricedRequest()

    with pytest.raises(ValidationError, match="exactly one"):
        api.LpStatePricedRequest(lp_token_id=1, lp_token_ids=[2])


@pytest.mark.parametrize(
    "payload",
    [
        {"lp_token_id": 0},
        {"lp_token_id": -1},
        {"lp_token_id": True},
        {"lp_token_id": "1"},
        {"lp_token_ids": []},
        {"lp_token_ids": [1, -2]},
        {"lp_token_ids": [1, True]},
        {"lp_token_ids": [1, "2"]},
        {"lp_token_ids": list(range(1, 252))},
    ],
)
def test_lp_request_rejects_invalid_or_unbounded_ids(payload: dict) -> None:
    with pytest.raises(ValidationError):
        api.LpStatePricedRequest(**payload)


def test_lp_request_deduplicates_batch_without_reordering() -> None:
    request = api.LpStatePricedRequest(lp_token_ids=[8, 5, 8, 13])

    assert request.lp_token_ids == [8, 5, 13]


def test_lp_batch_uses_one_database_query_and_preserves_missing_entries(
    monkeypatch,
) -> None:
    class AssetPrices:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def get_many_by_query(self, query: dict) -> list[SimpleNamespace]:
            self.calls.append(query)
            return [
                _lp_price(8),
                _lp_price(13),
            ]

    asset_prices = AssetPrices()
    monkeypatch.setattr(
        api,
        "db",
        SimpleNamespace(asset_prices=asset_prices),
    )

    response = asyncio.run(
        api.handle_get_lp_state_priced(
            api.LpStatePricedRequest(lp_token_ids=[8, 5, 13]),
        ),
    )

    assert asset_prices.calls == [{"id": {"$in": [8, 5, 13]}}]
    assert response == {
        "results": {
            "8": {
                "token_id": 8,
                "token_price_algo": 1.25,
                "token_price_usd": 0.42,
            },
            "5": None,
            "13": {
                "token_id": 13,
                "token_price_algo": 2.5,
                "token_price_usd": 0.84,
            },
        },
    }


def test_lp_single_response_remains_backward_compatible(monkeypatch) -> None:
    asset_prices = SimpleNamespace(
        get_many_by_query=lambda query: [_lp_price(8)],
    )
    monkeypatch.setattr(
        api,
        "db",
        SimpleNamespace(asset_prices=asset_prices),
    )

    response = asyncio.run(
        api.handle_get_lp_state_priced(
            api.LpStatePricedRequest(lp_token_id=8),
        ),
    )

    assert response == {
        "token_id": 8,
        "token_price_algo": 1.25,
        "token_price_usd": 0.42,
    }


def test_lp_endpoint_hides_price_older_than_max_stale(monkeypatch) -> None:
    asset_prices = SimpleNamespace(
        get_many_by_query=lambda query: [
            _lp_price(8, age_seconds=api.settings.asset_prices_max_stale + 1),
        ],
    )
    monkeypatch.setattr(
        api,
        "db",
        SimpleNamespace(asset_prices=asset_prices),
    )

    response = asyncio.run(
        api.handle_get_lp_state_priced(
            api.LpStatePricedRequest(lp_token_id=8),
        ),
    )

    assert response is None


def test_asset_price_endpoint_maps_unavailable_price_to_503(monkeypatch) -> None:
    async def unavailable_price(asset_id: int):
        raise PriceUnavailableError("provider outage and stale fallback expired")

    monkeypatch.setattr(api, "get_asset_price", unavailable_price)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(api.handle_get_asset_price_by_id(42))

    assert raised.value.status_code == 503
    assert raised.value.detail == "Price for asset 42 is temporarily unavailable"
