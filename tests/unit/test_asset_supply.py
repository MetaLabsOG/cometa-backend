from collections.abc import Callable
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from flex.blockchain import info
from flex.data import assets as asset_data
from flex.db.model.blockchain import (
    TOTAL_SUPPLY_SOURCE_INDEXER,
    UINT64_MAX,
    Asset,
)


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
    assert stored["total_supply_source"] == TOTAL_SUPPLY_SOURCE_INDEXER
    restored = Asset.from_dict(stored)
    assert restored.total_supply_micros == total
    assert restored.total_supply_is_authoritative is True


def test_legacy_asset_document_marks_reconstructed_supply_non_authoritative() -> None:
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
    assert asset.total_supply_is_authoritative is False
    assert "total_supply_micros" not in asset.to_dict()


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
        total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
    )

    assert int(asset.total_supply) != canonical_supply
    assert asset.total_supply_micros == canonical_supply
    assert asset.total_supply_is_authoritative is True


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


class _AssetCollection:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.update_query: dict[str, Any] | None = None

    def find_one(
        self,
        query: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        if "_id" in query and query["_id"] != self.document["_id"]:
            return None
        result = deepcopy(self.document)
        if projection is None:
            return result
        return {key: value for key, value in result.items() if key == "_id" or projection.get(key)}

    def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        del kwargs
        self.update_query = query
        may_migrate = (
            self.document.get("total_supply_micros") is None
            or self.document.get("total_supply_source") != TOTAL_SUPPLY_SOURCE_INDEXER
        )
        if query["_id"] != self.document["_id"] or not may_migrate:
            return None
        self.document.update(update["$set"])
        return deepcopy(self.document)


class _AssetManager:
    def __init__(self, collection: _AssetCollection) -> None:
        self.mongodb_collection = collection

    def get_by_primary_key(
        self,
        asset_id: int,
        *,
        throw_ex: bool,
    ) -> Asset | None:
        del asset_id, throw_ex
        return Asset.from_dict(deepcopy(self.mongodb_collection.document))


@pytest.mark.asyncio
async def test_financial_supply_backfills_from_indexer_instead_of_legacy_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _AssetCollection(
        {
            "_id": "asset-42",
            "id": 42,
            "total_supply": float(UINT64_MAX),
        }
    )
    monkeypatch.setattr(
        asset_data,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(
                mongodb_collection=collection,
            )
        ),
    )
    authoritative = Asset(
        id=42,
        name="Canonical Asset",
        decimals=0,
        unit_name="CANON",
        creator="CREATOR",
        reserve="RESERVE",
        total_supply=0,
        total_supply_micros=UINT64_MAX,
        total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
    )
    fetches: list[int] = []

    async def fetch_asset(asset_id: int) -> Asset:
        fetches.append(asset_id)
        return authoritative

    monkeypatch.setattr(asset_data, "fetch_asset", fetch_asset)

    supply = await asset_data.get_asset_total_supply.__wrapped__(42)

    assert supply == UINT64_MAX
    assert fetches == [42]
    assert collection.document["total_supply_micros"] == str(UINT64_MAX)
    assert collection.document["total_supply_source"] == TOTAL_SUPPLY_SOURCE_INDEXER
    assert collection.update_query == {
        "_id": "asset-42",
        "$or": [
            {"total_supply_micros": {"$exists": False}},
            {"total_supply_micros": None},
            {"total_supply_source": {"$ne": TOTAL_SUPPLY_SOURCE_INDEXER}},
        ],
    }


@pytest.mark.asyncio
async def test_financial_supply_uses_persisted_canonical_units_without_indexer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _AssetCollection(
        {
            "_id": "asset-42",
            "id": 42,
            "total_supply": 1.0,
            "total_supply_micros": str(2**53 + 1),
            "total_supply_source": TOTAL_SUPPLY_SOURCE_INDEXER,
        }
    )
    monkeypatch.setattr(
        asset_data,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(
                mongodb_collection=collection,
            )
        ),
    )

    async def unexpected_fetch(asset_id: int) -> Asset:
        pytest.fail(f"unexpected Indexer read for asset {asset_id}")

    monkeypatch.setattr(asset_data, "fetch_asset", unexpected_fetch)

    supply = await asset_data.get_asset_total_supply.__wrapped__(42)

    assert supply == 2**53 + 1
    assert collection.update_query is None


@pytest.mark.asyncio
async def test_unverified_persisted_supply_is_overwritten_from_indexer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _AssetCollection(
        {
            "_id": "asset-42",
            "id": 42,
            "total_supply": float(2**53),
            "total_supply_micros": str(2**53),
            "total_supply_source": None,
        }
    )
    monkeypatch.setattr(
        asset_data,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(
                mongodb_collection=collection,
            )
        ),
    )
    authoritative_supply = 2**53 + 1

    async def fetch_asset(asset_id: int) -> Asset:
        assert asset_id == 42
        return Asset(
            id=42,
            name="Canonical Asset",
            decimals=0,
            unit_name="CANON",
            creator="CREATOR",
            reserve="RESERVE",
            total_supply=0,
            total_supply_micros=authoritative_supply,
            total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
        )

    monkeypatch.setattr(asset_data, "fetch_asset", fetch_asset)

    supply = await asset_data.get_asset_total_supply.__wrapped__(42)

    assert supply == authoritative_supply
    assert collection.document["total_supply_micros"] == str(authoritative_supply)
    assert collection.document["total_supply_source"] == TOTAL_SUPPLY_SOURCE_INDEXER


@pytest.mark.asyncio
async def test_full_asset_read_migrates_legacy_supply_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = _AssetCollection(
        {
            "_id": "asset-42",
            "id": 42,
            "name": "Legacy Asset",
            "decimals": 0,
            "unit_name": "OLD",
            "creator": "CREATOR",
            "reserve": "RESERVE",
            "total_supply": float(UINT64_MAX),
        }
    )
    manager = _AssetManager(collection)
    monkeypatch.setattr(
        asset_data,
        "db",
        SimpleNamespace(assets=manager),
    )

    async def fetch_asset(asset_id: int) -> Asset:
        assert asset_id == 42
        return Asset(
            id=42,
            name="Canonical Asset",
            decimals=0,
            unit_name="CANON",
            creator="CREATOR",
            reserve="RESERVE",
            total_supply=0,
            total_supply_micros=UINT64_MAX,
            total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
        )

    monkeypatch.setattr(asset_data, "fetch_asset", fetch_asset)

    asset = await asset_data.get_full_asset.__wrapped__(42)

    assert asset.total_supply_micros == UINT64_MAX
    assert asset.total_supply_is_authoritative is True
