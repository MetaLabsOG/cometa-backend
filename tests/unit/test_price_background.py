import asyncio
from types import SimpleNamespace

import pytest

from api import background
from flex.data import lp_registry


def _empty_price_database() -> SimpleNamespace:
    return SimpleNamespace(
        assets=SimpleNamespace(get_all=lambda: []),
        asset_prices=SimpleNamespace(get_all=lambda: []),
    )


def test_retired_lp_price_flag_cannot_enable_a_publisher(monkeypatch) -> None:
    monkeypatch.setattr(background.settings, "background_asset_prices_update", True)
    monkeypatch.setattr(background.settings, "background_lp_prices_update", True)
    monkeypatch.setattr(background, "db", _empty_price_database())
    monkeypatch.setattr(background, "get_current_round", lambda: 321)

    async def no_lp_definitions() -> list[dict]:
        return []

    monkeypatch.setattr(
        background,
        "get_lp_token_definitions",
        no_lp_definitions,
    )

    one_shot = background.update_asset_prices_background.__wrapped__.__wrapped__
    asyncio.run(one_shot())

    assert not hasattr(background, "update_lp_token_prices")


def test_lp_registry_failure_keeps_generic_refresh_fail_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(background.settings, "background_asset_prices_update", True)
    monkeypatch.setattr(background.settings, "background_lp_prices_update", False)
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

    one_shot = background.update_asset_prices_background.__wrapped__.__wrapped__
    asyncio.run(one_shot())


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "stake_token_id": 999,
            "asset1_id": 7,
            "asset2_id": 0,
        },
        {
            "stake_token_id": 999,
        },
    ],
)
def test_incomplete_lp_registry_fails_closed(
    monkeypatch,
    metadata: dict,
) -> None:
    contract = SimpleNamespace(
        metadata=metadata,
    )
    monkeypatch.setattr(
        lp_registry,
        "get_contracts_by_type",
        lambda contract_type: [contract],
    )
    monkeypatch.setattr(
        lp_registry,
        "db",
        SimpleNamespace(
            lp_tokens=SimpleNamespace(
                get_many_by_query=lambda query: [],
            ),
            farming_pools=SimpleNamespace(get_all=lambda: []),
        ),
    )

    with pytest.raises(
        lp_registry.LpTokenRegistryError,
        match=r"classification is incomplete.*999",
    ):
        asyncio.run(lp_registry.get_lp_token_definitions.__wrapped__())
