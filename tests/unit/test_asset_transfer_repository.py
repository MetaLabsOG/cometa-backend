from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from bson import Decimal128
from pymongo import ReturnDocument

from flex.db.asset_transfer_intents import (
    MongoAssetTransferIntentRepository,
    TransferIntentPersistenceError,
)
from flex.db.model.transfers import AssetTransferIntent


def _intent() -> AssetTransferIntent:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return AssetTransferIntent(
        id="airdrop:summer:address",
        receiver="address",
        asset_id="42",
        amount_micros="1000",
        note="hello",
        signed_transaction="signed",
        txid="txid",
        first_valid_round=100,
        last_valid_round=1_100,
        status="prepared",
        created=timestamp,
        updated=timestamp,
    )


def test_repository_installs_unique_and_reconciliation_indexes() -> None:
    collection = Mock()
    repository = MongoAssetTransferIntentRepository(collection)

    repository.ensure_indexes()

    collection.create_index.assert_any_call("id", unique=True, name="id_unique")
    collection.create_index.assert_any_call(
        [("status", 1), ("updated", 1)],
        name="status_updated_idx",
    )


def test_reserve_uses_one_atomic_set_on_insert() -> None:
    collection = Mock()
    intent = _intent()
    collection.find_one_and_update.return_value = intent.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    reserved = repository.reserve(intent)

    assert reserved == intent
    collection.find_one_and_update.assert_called_once_with(
        {"id": intent.id},
        {"$setOnInsert": intent.to_dict()},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def test_confirmation_is_guarded_by_operation_and_transaction_id() -> None:
    collection = Mock()
    confirmed = _intent()
    confirmed.status = "confirmed"
    confirmed.confirmed_round = 777
    collection.find_one_and_update.return_value = confirmed.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    result = repository.mark_confirmed(
        confirmed.id,
        confirmed.txid,
        confirmed.confirmed_round,
    )

    assert result.status == "confirmed"
    assert result.confirmed_round == 777
    args, kwargs = collection.find_one_and_update.call_args
    assert args[0] == {
        "id": confirmed.id,
        "txid": confirmed.txid,
        "status": {"$ne": "confirmed"},
    }
    assert args[1]["$set"]["status"] == "confirmed"
    assert args[1]["$set"]["confirmed_round"] == Decimal128("777")
    assert kwargs == {"return_document": ReturnDocument.AFTER}


def test_repeated_identical_confirmation_preserves_terminal_evidence() -> None:
    collection = Mock()
    confirmed = _intent()
    confirmed.status = "confirmed"
    confirmed.confirmed_round = 777
    confirmed.confirmed_at = datetime(2026, 1, 2, tzinfo=UTC)
    collection.find_one_and_update.return_value = None
    collection.find_one.return_value = confirmed.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    result = repository.mark_confirmed(confirmed.id, confirmed.txid, 777)

    assert result == confirmed
    assert result.confirmed_at == datetime(2026, 1, 2, tzinfo=UTC)
    query = collection.find_one_and_update.call_args.args[0]
    assert query["status"] == {"$ne": "confirmed"}
    collection.find_one.assert_called_once_with({"id": confirmed.id})


@pytest.mark.parametrize(
    ("current", "txid", "round_number", "message"),
    [
        (None, "txid", 777, "no longer exists"),
        (_intent(), "other-txid", 777, "now belongs to transaction"),
        (_intent(), "txid", 778, "already confirmed in round"),
        (_intent(), "txid", 777, "remains in status"),
    ],
)
def test_confirmation_cas_miss_fails_closed(
    current: AssetTransferIntent | None,
    txid: str,
    round_number: int,
    message: str,
) -> None:
    if current is not None and message == "already confirmed in round":
        current.status = "confirmed"
        current.confirmed_round = 777
    collection = Mock()
    collection.find_one_and_update.return_value = None
    collection.find_one.return_value = None if current is None else current.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    with pytest.raises(TransferIntentPersistenceError, match=message):
        repository.mark_confirmed("airdrop:summer:address", txid, round_number)


@pytest.mark.parametrize(
    "update",
    [
        lambda repository, intent: repository.record_attempt(intent.id, intent.txid),
        lambda repository, intent: repository.mark_submitted(intent.id, intent.txid),
        lambda repository, intent: repository.record_error(intent.id, intent.txid, "late error"),
    ],
)
def test_non_confirmation_updates_cannot_mutate_confirmed_intent(update) -> None:
    collection = Mock()
    confirmed = _intent()
    confirmed.status = "confirmed"
    confirmed.attempt_count = 4
    confirmed.confirmed_round = 777
    collection.find_one_and_update.return_value = None
    collection.find_one.return_value = confirmed.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    result = update(repository, confirmed)

    assert result == confirmed
    query = collection.find_one_and_update.call_args.args[0]
    assert query == {
        "id": confirmed.id,
        "txid": confirmed.txid,
        "status": {"$ne": "confirmed"},
    }
    collection.find_one.assert_called_once_with({"id": confirmed.id})


@pytest.mark.parametrize(
    "update",
    [
        lambda repository, intent: repository.record_attempt(intent.id, "other-txid"),
        lambda repository, intent: repository.mark_submitted(intent.id, "other-txid"),
        lambda repository, intent: repository.record_error(intent.id, "other-txid", "late error"),
    ],
)
def test_non_confirmation_update_rejects_transaction_mismatch(update) -> None:
    collection = Mock()
    confirmed = _intent()
    confirmed.status = "confirmed"
    confirmed.confirmed_round = 777
    collection.find_one_and_update.return_value = None
    collection.find_one.return_value = confirmed.to_dict()
    repository = MongoAssetTransferIntentRepository(collection)

    with pytest.raises(TransferIntentPersistenceError, match="changed while updating"):
        update(repository, confirmed)
