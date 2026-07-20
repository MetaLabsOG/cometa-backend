from datetime import datetime

import pytest

from core.db.model import ContractInfo
from flex.application import pool_registration
from flex.db.model.blockchain import AssetInfo


@pytest.mark.asyncio
async def test_farming_pool_uses_synchronous_round_provider_for_missing_dates(monkeypatch):
    contract = ContractInfo(
        type="farm",
        id=42,
        version="0.1.11",
        deployed_timestamp=1_700_000_000,
        description="Test pool",
        metadata={
            "asset1_id": 1,
            "asset2_id": 2,
            "stake_token_id": 3,
            "reward_token_id": 4,
            "dex": "tinyman",
            "begin_block": 90,
            "end_block": 110,
            "lock_length_blocks": 5,
            "cache": {
                "initial": {
                    "totalRewardAmount": "1000",
                    "totalAlgoRewardAmount": "2000",
                }
            },
        },
    )
    observed_rounds: list[tuple[int, int]] = []

    async def fake_asset_info(asset_id: int) -> AssetInfo:
        return AssetInfo(
            id=asset_id,
            name=f"Asset {asset_id}",
            decimals=6,
            unit_name=f"A{asset_id}",
        )

    def fake_date_from_block(round_num: int, current_round: int, current_date: datetime) -> datetime:
        observed_rounds.append((round_num, current_round))
        return current_date

    monkeypatch.setattr(pool_registration, "get_current_round", lambda: 100)
    monkeypatch.setattr(pool_registration, "date_from_block", fake_date_from_block)
    monkeypatch.setattr(pool_registration, "get_asset_info", fake_asset_info)
    monkeypatch.setattr(pool_registration, "get_app_address", lambda _: _async_value("POOL"))

    pool = await pool_registration.farming_pool_from_contract_info(contract)

    assert pool.id == contract.id
    assert pool.address == "POOL"
    assert observed_rounds == [(90, 100), (110, 100)]


async def _async_value(value: str) -> str:
    return value
