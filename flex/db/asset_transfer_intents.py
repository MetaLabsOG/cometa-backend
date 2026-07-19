"""MongoDB repository for persisted outbound transfer intents."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from flex.db.model.transfers import AssetTransferIntent


class TransferIntentPersistenceError(RuntimeError):
    """Raised when an expected transfer intent cannot be persisted."""


@dataclass(slots=True)
class MongoAssetTransferIntentRepository:
    collection: Collection[dict[str, Any]]

    def ensure_indexes(self) -> None:
        self.collection.create_index("id", unique=True, name="id_unique")
        self.collection.create_index(
            [("status", 1), ("updated", 1)],
            name="status_updated_idx",
        )

    def get(self, operation_id: str) -> AssetTransferIntent | None:
        document = self.collection.find_one({"id": operation_id})
        return self._from_document(document)

    def reserve(self, intent: AssetTransferIntent) -> AssetTransferIntent:
        try:
            document = self.collection.find_one_and_update(
                {"id": intent.id},
                {"$setOnInsert": intent.to_dict()},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            document = self.collection.find_one({"id": intent.id})
        reserved = self._from_document(document)
        if reserved is None:
            raise TransferIntentPersistenceError(f"failed to reserve transfer {intent.id!r}")
        return reserved

    def record_attempt(self, operation_id: str, txid: str) -> AssetTransferIntent:
        return self._update(
            operation_id,
            txid,
            {
                "$inc": {"attempt_count": 1},
                "$set": {"updated": datetime.now(UTC)},
            },
        )

    def mark_submitted(self, operation_id: str, txid: str) -> AssetTransferIntent:
        now = datetime.now(UTC)
        return self._update(
            operation_id,
            txid,
            {
                "$set": {
                    "status": "submitted",
                    "submitted_at": now,
                    "last_error": None,
                    "updated": now,
                }
            },
        )

    def mark_confirmed(
        self,
        operation_id: str,
        txid: str,
        confirmed_round: int,
    ) -> AssetTransferIntent:
        now = datetime.now(UTC)
        return self._update(
            operation_id,
            txid,
            {
                "$set": {
                    "status": "confirmed",
                    "confirmed_round": confirmed_round,
                    "confirmed_at": now,
                    "last_error": None,
                    "updated": now,
                }
            },
        )

    def record_error(
        self,
        operation_id: str,
        txid: str,
        error: str,
    ) -> AssetTransferIntent:
        return self._update(
            operation_id,
            txid,
            {
                "$set": {
                    "last_error": error[:500],
                    "updated": datetime.now(UTC),
                }
            },
        )

    def _update(
        self,
        operation_id: str,
        txid: str,
        update: dict[str, Any],
    ) -> AssetTransferIntent:
        document = self.collection.find_one_and_update(
            {"id": operation_id, "txid": txid},
            update,
            return_document=ReturnDocument.AFTER,
        )
        intent = self._from_document(document)
        if intent is None:
            raise TransferIntentPersistenceError(f"transfer {operation_id!r} changed while updating transaction {txid}")
        return intent

    @staticmethod
    def _from_document(
        document: dict[str, Any] | None,
    ) -> AssetTransferIntent | None:
        if document is None:
            return None
        payload = dict(document)
        payload.pop("_id", None)
        return AssetTransferIntent.from_dict(payload)
