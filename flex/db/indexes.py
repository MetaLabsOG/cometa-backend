import logging
from collections.abc import Sequence
from typing import Any

from pymongo.collection import Collection

from flex.db.cometa_database import CometaDatabase

logger = logging.getLogger(__name__)

_UNIQUE_ID_POLICIES = (
    ("airdrop_manifests", False),
    ("asset_prices", True),
    ("asset_transfer_intents", False),
    ("pool_transactions", False),
    ("lp_transactions", False),
)

_HOT_INDEXES = (
    ("lp_states", "token_id", "token_id_unique"),
    ("lp_states", "address", "address_unique"),
    ("pool_states", "pool_id", "pool_id_idx"),
    ("user_states", "address", "address_idx"),
    ("lp_tokens", "id", "lp_token_id_idx"),
)


def _duplicate_field_pipeline(field_name: str) -> list[dict[str, Any]]:
    """Group duplicate business keys after sorting the newest record first."""

    return [
        {
            "$sort": {
                field_name: 1,
                "observed_at": -1,
                "updated": -1,
                "_id": -1,
            }
        },
        {
            "$group": {
                "_id": f"${field_name}",
                "count": {"$sum": 1},
                "keep_id": {"$first": "$_id"},
                "all_ids": {"$push": "$_id"},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]


def deduplicate_and_create_unique_id_index(
    collection: Collection[dict[str, Any]],
    *,
    collection_name: str,
) -> int:
    """Keep the newest document per ID, then enforce uniqueness."""
    removed = 0
    duplicate_groups: Sequence[dict[str, Any]] = list(
        collection.aggregate(
            _duplicate_field_pipeline("id"),
            allowDiskUse=True,
        )
    )

    for group in duplicate_groups:
        duplicate_ids = [document_id for document_id in group["all_ids"] if document_id != group["keep_id"]]
        if duplicate_ids:
            result = collection.delete_many({"_id": {"$in": duplicate_ids}})
            removed += result.deleted_count

    collection.create_index("id", unique=True, name="id_unique")
    logger.info(
        "Ensured unique index on %s.id after removing %d duplicate document(s)",
        collection_name,
        removed,
    )
    return removed


def create_unique_id_index_fail_closed(
    collection: Collection[dict[str, Any]],
    *,
    collection_name: str,
) -> None:
    """Preserve conflicting immutable records for explicit reconciliation."""

    duplicate_groups: Sequence[dict[str, Any]] = list(
        collection.aggregate(
            _duplicate_field_pipeline("id"),
            allowDiskUse=True,
        )
    )
    if duplicate_groups:
        raise RuntimeError(
            f"{collection_name} contains {len(duplicate_groups)} duplicate immutable ID group(s); "
            "reconcile or quarantine them before startup"
        )
    collection.create_index("id", unique=True, name="id_unique")


def create_unique_field_index_fail_closed(
    collection: Collection[dict[str, Any]],
    *,
    collection_name: str,
    field_name: str,
    index_name: str,
) -> None:
    """Enforce aggregate identity without destroying conflicting state."""

    duplicate_groups: Sequence[dict[str, Any]] = list(
        collection.aggregate(
            _duplicate_field_pipeline(field_name),
            allowDiskUse=True,
        )
    )
    if duplicate_groups:
        raise RuntimeError(
            f"{collection_name} contains {len(duplicate_groups)} duplicate {field_name!r} group(s); "
            "reconcile them before startup"
        )
    collection.create_index(
        field_name,
        unique=True,
        name=index_name,
    )


def ensure_sync_state_singleton(database: CometaDatabase) -> None:
    """Migrate one legacy random-ID cursor and reject competing checkpoints."""

    collection = database.sync_states.mongodb_collection
    documents = list(
        collection.find(
            {},
            projection={"_id": 1, "id": 1, "last_round": 1},
        )
    )
    if len(documents) > 1:
        raise RuntimeError(
            f"sync_states contains {len(documents)} competing checkpoints; reconcile them before startup"
        )
    if documents and documents[0].get("id") != "main":
        collection.update_one(
            {"_id": documents[0]["_id"]},
            {"$set": {"id": "main"}},
        )
    collection.create_index("id", unique=True, name="id_unique")


def ensure_database_indexes(database: CometaDatabase) -> dict[str, int]:
    """Install correctness-critical unique indexes and hot query indexes."""
    removed_by_collection: dict[str, int] = {}

    for collection_name, can_deduplicate in _UNIQUE_ID_POLICIES:
        manager = getattr(database, collection_name)
        if can_deduplicate:
            removed_by_collection[collection_name] = deduplicate_and_create_unique_id_index(
                manager.mongodb_collection,
                collection_name=collection_name,
            )
        else:
            create_unique_id_index_fail_closed(
                manager.mongodb_collection,
                collection_name=collection_name,
            )
            removed_by_collection[collection_name] = 0

    ensure_sync_state_singleton(database)

    for manager_name, field_name, index_name in _HOT_INDEXES:
        manager = getattr(database, manager_name)
        if manager_name == "lp_states":
            create_unique_field_index_fail_closed(
                manager.mongodb_collection,
                collection_name=manager_name,
                field_name=field_name,
                index_name=index_name,
            )
        else:
            manager.mongodb_collection.create_index(field_name, name=index_name)

    database.airdrop_rewards.mongodb_collection.create_index(
        "operation_id",
        unique=True,
        name="operation_id_unique",
        partialFilterExpression={"operation_id": {"$type": "string"}},
    )

    logger.info("Ensured hot query indexes for Flex collections")
    return removed_by_collection
