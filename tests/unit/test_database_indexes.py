from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from flex.db.indexes import (
    create_unique_id_index_fail_closed,
    deduplicate_and_create_unique_id_index,
    ensure_database_indexes,
    ensure_sync_state_singleton,
)


def _manager(collection: Mock) -> SimpleNamespace:
    return SimpleNamespace(mongodb_collection=collection)


def _database(**collections: Mock) -> SimpleNamespace:
    names = (
        "airdrop_manifests",
        "asset_prices",
        "asset_transfer_intents",
        "pool_transactions",
        "lp_transactions",
        "lp_states",
        "pool_states",
        "user_states",
        "lp_tokens",
        "airdrop_rewards",
        "sync_states",
    )
    return SimpleNamespace(**{name: _manager(collections.get(name, Mock())) for name in names})


def test_deduplication_keeps_newest_record_before_creating_index() -> None:
    collection = Mock()
    collection.aggregate.return_value = [
        {
            "_id": 42,
            "count": 3,
            "keep_id": "newest",
            "all_ids": ["newest", "older", "oldest"],
        }
    ]
    collection.delete_many.return_value = SimpleNamespace(deleted_count=2)

    removed = deduplicate_and_create_unique_id_index(
        collection,
        collection_name="asset_prices",
    )

    assert removed == 2
    pipeline = collection.aggregate.call_args.args[0]
    assert pipeline[0] == {
        "$sort": {
            "id": 1,
            "observed_at": -1,
            "updated": -1,
            "_id": -1,
        }
    }
    assert pipeline[1]["$group"]["keep_id"] == {"$first": "$_id"}
    assert collection.aggregate.call_args.kwargs == {"allowDiskUse": True}
    collection.delete_many.assert_called_once_with({"_id": {"$in": ["older", "oldest"]}})
    collection.create_index.assert_called_once_with("id", unique=True, name="id_unique")
    assert collection.mock_calls.index(
        call.delete_many({"_id": {"$in": ["older", "oldest"]}})
    ) < collection.mock_calls.index(call.create_index("id", unique=True, name="id_unique"))


def test_immutable_ledger_duplicates_abort_without_deleting_evidence() -> None:
    collection = Mock()
    collection.aggregate.return_value = [
        {
            "_id": "operation",
            "count": 2,
            "keep_id": "confirmed",
            "all_ids": ["confirmed", "prepared"],
        }
    ]

    with pytest.raises(RuntimeError, match="duplicate immutable ID"):
        create_unique_id_index_fail_closed(
            collection,
            collection_name="asset_transfer_intents",
        )

    collection.delete_many.assert_not_called()
    collection.create_index.assert_not_called()


def test_database_indexes_cover_all_projection_ids_and_hot_queries() -> None:
    unique_collections = {
        name: Mock()
        for name in (
            "airdrop_manifests",
            "asset_prices",
            "asset_transfer_intents",
            "pool_transactions",
            "lp_transactions",
        )
    }
    for collection in unique_collections.values():
        collection.aggregate.return_value = []
    lp_states = Mock()
    lp_states.aggregate.return_value = []
    sync_states = Mock()
    sync_states.find.return_value = []

    database = _database(
        **unique_collections,
        lp_states=lp_states,
        sync_states=sync_states,
    )

    removed = ensure_database_indexes(database)

    assert removed == {
        "airdrop_manifests": 0,
        "asset_prices": 0,
        "asset_transfer_intents": 0,
        "pool_transactions": 0,
        "lp_transactions": 0,
    }
    for collection in unique_collections.values():
        collection.create_index.assert_called_once_with("id", unique=True, name="id_unique")

    assert database.lp_states.mongodb_collection.create_index.call_args_list == [
        call("token_id", unique=True, name="token_id_unique"),
        call("address", unique=True, name="address_unique"),
    ]
    database.pool_states.mongodb_collection.create_index.assert_called_once_with("pool_id", name="pool_id_idx")
    database.user_states.mongodb_collection.create_index.assert_called_once_with("address", name="address_idx")
    database.lp_tokens.mongodb_collection.create_index.assert_called_once_with("id", name="lp_token_id_idx")
    database.airdrop_rewards.mongodb_collection.create_index.assert_called_once_with(
        "operation_id",
        unique=True,
        name="operation_id_unique",
        partialFilterExpression={"operation_id": {"$type": "string"}},
    )
    database.sync_states.mongodb_collection.create_index.assert_called_once_with(
        "id",
        unique=True,
        name="id_unique",
    )


def test_single_legacy_sync_cursor_is_migrated_without_guessing_between_competitors() -> None:
    collection = Mock()
    collection.find.return_value = [
        {
            "_id": "mongo-id",
            "id": "legacy-random-id",
            "last_round": 123,
        }
    ]
    database = _database(sync_states=collection)

    ensure_sync_state_singleton(database)

    collection.update_one.assert_called_once_with(
        {"_id": "mongo-id"},
        {"$set": {"id": "main"}},
    )
    collection.create_index.assert_called_once_with(
        "id",
        unique=True,
        name="id_unique",
    )


def test_competing_sync_cursors_fail_closed() -> None:
    collection = Mock()
    collection.find.return_value = [
        {"_id": "a", "id": "a", "last_round": 100},
        {"_id": "b", "id": "b", "last_round": 101},
    ]

    with pytest.raises(RuntimeError, match="competing checkpoints"):
        ensure_sync_state_singleton(
            _database(sync_states=collection),
        )

    collection.update_one.assert_not_called()
    collection.create_index.assert_not_called()


def test_correctness_critical_index_failure_is_not_swallowed() -> None:
    database = _database()
    database.airdrop_manifests.mongodb_collection.aggregate.return_value = []
    database.asset_prices.mongodb_collection.aggregate.return_value = []
    database.asset_prices.mongodb_collection.create_index.side_effect = RuntimeError("index build failed")

    with pytest.raises(RuntimeError, match="index build failed"):
        ensure_database_indexes(database)

    database.pool_transactions.mongodb_collection.aggregate.assert_not_called()
    database.lp_states.mongodb_collection.create_index.assert_not_called()
