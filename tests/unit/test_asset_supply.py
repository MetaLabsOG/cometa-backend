from collections.abc import Callable
from typing import Any

import pytest

from flex.blockchain import info
from flex.db.model.blockchain import UINT64_MAX, Asset


def _asset_response(*, total: int, decimals: int) -> dict[str, Any]:
    return {
        "asset": {
            "params": {
                "creator": "CREATOR",
                "decimals": decimals,
                "name": "Precision Asset",
                "reserve": "RESERVE",
                "total": total,
                "unit-name": "PRECISE",
            }
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [2**53 + 1, UINT64_MAX])
async def test_fetch_asset_preserves_full_uint64_supply(
    monkeypatch: pytest.MonkeyPatch,
    total: int,
) -> None:
    async def fake_run_sync(func: Callable[..., Any], *args: Any) -> dict[str, Any]:
        del func, args
        return _asset_response(total=total, decimals=0)

    monkeypatch.setattr(info, "_run_sync", fake_run_sync)

    asset = await info.fetch_asset(42)

    assert asset.total_supply_micros == total
    assert asset.total_supply_base_units == total

    stored = asset.to_dict()
    assert stored["total_supply_micros"] == str(total)
    assert Asset.from_dict(stored).total_supply_micros == total


def test_legacy_asset_document_backfills_canonical_supply() -> None:
    legacy_document = {
        "id": 42,
        "name": "Legacy Asset",
        "decimals": 6,
        "unit_name": "OLD",
        "creator": "CREATOR",
        "reserve": "RESERVE",
        "total_supply": 123.456789,
    }

    asset = Asset.from_dict(legacy_document)

    assert asset.total_supply_micros == 123_456_789
    assert asset.to_dict()["total_supply_micros"] == "123456789"


def test_canonical_supply_wins_over_lossy_legacy_float() -> None:
    canonical_supply = 2**53 + 1

    asset = Asset(
        id=42,
        name="Canonical Asset",
        decimals=0,
        unit_name="CANON",
        creator="CREATOR",
        reserve="RESERVE",
        total_supply=float(canonical_supply),
        total_supply_micros=canonical_supply,
    )

    assert int(asset.total_supply) != canonical_supply
    assert asset.total_supply_micros == canonical_supply


@pytest.mark.parametrize("invalid_supply", [-1, UINT64_MAX + 1])
def test_asset_rejects_supply_outside_algorand_uint64(invalid_supply: int) -> None:
    with pytest.raises(ValueError, match="total_supply_micros"):
        Asset(
            id=42,
            name="Invalid Asset",
            decimals=0,
            unit_name="BAD",
            creator="CREATOR",
            reserve="RESERVE",
            total_supply=0,
            total_supply_micros=invalid_supply,
        )
