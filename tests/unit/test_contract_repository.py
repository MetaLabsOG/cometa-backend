from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymongo.errors import DuplicateKeyError

from core.db.contracts import (
    ContractIdentityConflictError,
    ensure_contract_id_index,
    get_or_create_contract,
)
from core.db.model import ContractInfo


def _contract(*, contract_type: str = "farm", version: str = "17.2.5") -> ContractInfo:
    deployed_at = datetime(2026, 1, 1, tzinfo=UTC)
    return ContractInfo(
        type=contract_type,
        id=42,
        version=version,
        deployed_timestamp=deployed_at.timestamp(),
        deployed_date=deployed_at,
        description="Test contract",
        metadata={"cache": {"initial": {}}},
    )


def test_contract_index_fails_closed_on_duplicate_identity() -> None:
    collection = Mock()
    collection.aggregate.return_value = [{"_id": 42, "count": 2}]

    with pytest.raises(RuntimeError, match="duplicate immutable ID 42"):
        ensure_contract_id_index(target_collection=collection)

    collection.create_index.assert_not_called()


def test_contract_index_enforces_unique_business_id() -> None:
    collection = Mock()
    collection.aggregate.return_value = []

    ensure_contract_id_index(target_collection=collection)

    collection.create_index.assert_called_once_with(
        "id",
        unique=True,
        name="contract_id_unique",
    )


def test_contract_upsert_returns_canonical_existing_record() -> None:
    requested = _contract()
    existing = _contract()
    existing.description = "Canonical description"
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(upserted_id=None)
    collection.find_one.return_value = existing.to_dict()

    result = get_or_create_contract(
        requested,
        target_collection=collection,
    )

    assert result.contract.description == "Canonical description"
    assert result.created is False
    collection.update_one.assert_called_once_with(
        {"id": requested.id},
        {"$setOnInsert": requested.to_dict()},
        upsert=True,
    )


def test_contract_upsert_recovers_after_concurrent_unique_insert() -> None:
    contract = _contract()
    collection = Mock()
    collection.update_one.side_effect = DuplicateKeyError("concurrent insert")
    collection.find_one.return_value = contract.to_dict()

    result = get_or_create_contract(
        contract,
        target_collection=collection,
    )

    assert result.contract.id == contract.id
    assert result.created is False


def test_contract_upsert_rejects_conflicting_identity() -> None:
    requested = _contract(version="17.2.5")
    existing = _contract(version="17.2.4")
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(upserted_id=None)
    collection.find_one.return_value = existing.to_dict()

    with pytest.raises(ContractIdentityConflictError, match="different type or version"):
        get_or_create_contract(
            requested,
            target_collection=collection,
        )
