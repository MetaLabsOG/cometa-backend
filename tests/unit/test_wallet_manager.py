import time
from concurrent.futures import ThreadPoolExecutor

from api import wallet_manager
from core.tinychart import Price


def test_wallet_asset_lookup_is_bounded_and_keeps_algo(monkeypatch):
    wallet_manager.get_wallet_assets.cache_clear()
    holdings = [
        {
            "asset-id": asset_id,
            "amount": 1_000_000,
            "deleted": False,
        }
        for asset_id in range(1, 151)
    ]
    holdings.append(
        {
            "asset-id": 0,
            "amount": 2_000_000,
            "deleted": False,
        },
    )
    account_calls = 0

    def fake_account_assets(address: str) -> list[dict]:
        nonlocal account_calls
        account_calls += 1
        return holdings

    monkeypatch.setattr(wallet_manager, "get_account_assets", fake_account_assets)
    monkeypatch.setattr(
        wallet_manager,
        "get_asset_info",
        lambda asset_id: {
            "name": f"Asset {asset_id}",
            "unit_name": f"A{asset_id}",
            "decimals": 6,
        },
    )
    monkeypatch.setattr(
        wallet_manager.tinychart,
        "get_asset_price_full",
        lambda asset_id: Price(usd=1.0, microalgo=1_000_000),
    )

    first = wallet_manager.get_wallet_assets("valid-test-address")
    second = wallet_manager.get_wallet_assets("valid-test-address")

    assert len(first) == wallet_manager.MAX_WALLET_ASSETS
    assert [asset.asset_id for asset in first] == list(range(100))
    assert second == first
    assert account_calls == 1


def test_wallet_asset_cache_coalesces_concurrent_misses(monkeypatch):
    wallet_manager.get_wallet_assets.cache_clear()
    account_calls = 0

    def fake_account_assets(address: str) -> list[dict]:
        nonlocal account_calls
        account_calls += 1
        time.sleep(0.05)
        return [{"asset-id": 0, "amount": 1_000_000, "deleted": False}]

    monkeypatch.setattr(wallet_manager, "get_account_assets", fake_account_assets)
    monkeypatch.setattr(
        wallet_manager,
        "get_asset_info",
        lambda asset_id: {"name": "Algorand", "unit_name": "ALGO", "decimals": 6},
    )
    monkeypatch.setattr(
        wallet_manager.tinychart,
        "get_asset_price_full",
        lambda asset_id: Price(usd=1.0, microalgo=1_000_000),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                wallet_manager.get_wallet_assets,
                ["same-address", "same-address"],
            ),
        )

    assert results[0] == results[1]
    assert account_calls == 1
