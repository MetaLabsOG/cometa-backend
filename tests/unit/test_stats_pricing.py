import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from flex.data import stats
from flex.db.model.pools import PoolType
from flex.db.model.priced import AssetPrice


def test_tvl_never_uses_legacy_raw_lp_projection(monkeypatch) -> None:
    legacy_price = AssetPrice(
        id=42,
        name="LEGACY",
        price_algo=999.0,
        price_usd=999.0,
        last_update_round=123,
        tinyman_algo_pool_id=777,
        source="tinyman",
        observed_at=datetime.now(UTC),
    )
    pool = SimpleNamespace(
        pool_id=1,
        stake_token=SimpleNamespace(id=42),
        total_staked=10,
    )
    requested_asset_ids = []

    async def safe_price(asset_id: int):
        requested_asset_ids.append(asset_id)
        return SimpleNamespace(price_usd=2.0)

    monkeypatch.setattr(
        stats,
        "db",
        SimpleNamespace(
            pool_states=SimpleNamespace(
                get_many=lambda **query: [pool],
            ),
            asset_prices=SimpleNamespace(get_all=lambda: [legacy_price]),
        ),
    )
    monkeypatch.setattr(stats, "get_asset_price", safe_price)

    total = asyncio.run(
        stats.calculate_total_tvl_usd_for_type(PoolType.FARMING),
    )

    assert total == 20.0
    assert requested_asset_ids == [42]
