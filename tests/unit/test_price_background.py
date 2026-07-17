import asyncio
from types import SimpleNamespace

import pytest

from api import background
from flex.data import lp_prices


def test_empty_asset_catalog_still_updates_lp_prices(monkeypatch) -> None:
    monkeypatch.setattr(background.settings, "background_asset_prices_update", True)
    monkeypatch.setattr(
        background,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(get_all=lambda: []),
            asset_prices=SimpleNamespace(get_all=lambda: []),
        ),
    )
    monkeypatch.setattr(background, "get_current_round", lambda: 321)

    async def no_lp_definitions() -> list[dict]:
        return []

    updated_rounds: list[int] = []

    async def record_lp_update(current_round: int) -> None:
        updated_rounds.append(current_round)

    monkeypatch.setattr(
        background,
        "get_lp_token_definitions",
        no_lp_definitions,
    )
    monkeypatch.setattr(background, "update_lp_token_prices", record_lp_update)

    one_shot = background.update_asset_prices_background.__wrapped__.__wrapped__
    asyncio.run(one_shot())

    assert updated_rounds == [321]


def test_lp_registry_failure_cannot_overwrite_lp_with_external_price(
    monkeypatch,
) -> None:
    monkeypatch.setattr(background.settings, "background_asset_prices_update", True)
    monkeypatch.setattr(
        background,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(
                get_all=lambda: [SimpleNamespace(id=999)],
            ),
            asset_prices=SimpleNamespace(get_all=lambda: []),
        ),
    )
    monkeypatch.setattr(background, "get_current_round", lambda: 321)

    async def failed_lp_registry() -> list[dict]:
        raise RuntimeError("database unavailable")

    async def unexpected_asset_refresh(*args, **kwargs):
        raise AssertionError("regular asset refresh must fail closed")

    updated_rounds: list[int] = []

    async def record_lp_update(current_round: int) -> None:
        updated_rounds.append(current_round)

    monkeypatch.setattr(
        background,
        "get_lp_token_definitions",
        failed_lp_registry,
    )
    monkeypatch.setattr(
        background,
        "create_asset_price",
        unexpected_asset_refresh,
    )
    monkeypatch.setattr(background, "update_lp_token_prices", record_lp_update)

    one_shot = background.update_asset_prices_background.__wrapped__.__wrapped__
    asyncio.run(one_shot())

    assert updated_rounds == [321]


def test_incomplete_lp_registry_fails_closed(monkeypatch) -> None:
    contract = SimpleNamespace(
        metadata={
            "stake_token_id": 999,
            "asset1_id": 7,
            "asset2_id": 0,
        },
    )
    monkeypatch.setattr(
        lp_prices,
        "get_contracts_by_type",
        lambda contract_type: [contract],
    )
    monkeypatch.setattr(
        lp_prices,
        "db",
        SimpleNamespace(
            lp_tokens=SimpleNamespace(
                get_many_by_query=lambda query: [],
            ),
            farming_pools=SimpleNamespace(get_all=lambda: []),
        ),
    )

    with pytest.raises(
        lp_prices.LpTokenRegistryError,
        match=r"incomplete.*999",
    ):
        asyncio.run(lp_prices.get_lp_token_definitions.__wrapped__())
