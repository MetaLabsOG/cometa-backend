import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import app as api_module
from flex.db.model.blockchain import AssetInfo
from flex.db.model.pools import StakingPool


def test_staking_pool_uses_reward_token_decimals() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    pool = StakingPool(
        description="different decimals",
        address="POOL",
        stake_token=AssetInfo(
            id=1,
            name="STAKE",
            unit_name="STK",
            decimals=6,
        ),
        reward_token=AssetInfo(
            id=2,
            name="REWARD",
            unit_name="RWD",
            decimals=2,
        ),
        reward_amount_micros=123,
        algo_reward_amount_micros=0,
        begin_block=1,
        end_block=2,
        lock_length_blocks=0,
        deploy_date=now,
        begin_date=now,
        end_date=now,
        id=3,
    )

    assert pool.to_info().reward_amount == 1.23


def test_contract_sorting_does_not_mutate_cached_repository_list(
    monkeypatch,
) -> None:
    cached = [
        SimpleNamespace(
            id=1,
            end_date=None,
            metadata={"cache": {"global": {"totalStaked": "0x1"}}},
        ),
        SimpleNamespace(
            id=2,
            end_date=None,
            metadata={"cache": {"global": {"totalStaked": "0x1"}}},
        ),
    ]
    monkeypatch.setattr(
        api_module,
        "get_contracts_by_type",
        lambda contract_type: cached,
    )

    newest_first = asyncio.run(
        api_module.get_contracts(
            type=None,
            max_count=None,
            new_first=True,
            without_old_pools=False,
            include_address_pools=None,
        )
    )
    original_order = asyncio.run(
        api_module.get_contracts(
            type=None,
            max_count=None,
            new_first=False,
            without_old_pools=False,
            include_address_pools=None,
        )
    )

    assert [contract.id for contract in newest_first] == [2, 1]
    assert [contract.id for contract in original_order] == [1, 2]
    assert [contract.id for contract in cached] == [1, 2]
