from datetime import UTC, datetime
from unittest.mock import Mock

from pymongo import ReturnDocument

from flex.db.asset_transfer_intents import MongoAssetTransferIntentRepository
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
    assert args[0] == {"id": confirmed.id, "txid": confirmed.txid}
    assert args[1]["$set"]["status"] == "confirmed"
    assert args[1]["$set"]["confirmed_round"] == 777
    assert kwargs == {"return_document": ReturnDocument.AFTER}
