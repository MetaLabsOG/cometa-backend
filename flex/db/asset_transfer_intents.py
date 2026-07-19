"""MongoDB repository for persisted outbound transfer intents."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from flex.db.bson import encode_bson_integer
from flex.db.model.transfers import AssetTransferIntent
from flex.domain.algorand import require_algorand_uint64


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
        return self._update_non_terminal(
            operation_id,
            txid,
            {
                "$inc": {"attempt_count": 1},
                "$set": {"updated": datetime.now(UTC)},
            },
        )

    def mark_submitted(self, operation_id: str, txid: str) -> AssetTransferIntent:
        now = datetime.now(UTC)
        return self._update_non_terminal(
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
        try:
            confirmed_round = require_algorand_uint64(
                confirmed_round,
                "confirmed_round",
            )
        except ValueError as exc:
            raise TransferIntentPersistenceError(str(exc)) from exc
        now = datetime.now(UTC)
        document = self.collection.find_one_and_update(
            {
                "id": operation_id,
                "txid": txid,
                "status": {"$ne": "confirmed"},
            },
            {
                "$set": {
                    "status": "confirmed",
                    "confirmed_round": encode_bson_integer(confirmed_round),
                    "confirmed_at": now,
                    "last_error": None,
                    "updated": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        intent = self._from_document(document)
        if intent is not None:
            return intent

        current = self.get(operation_id)
        if (
            current is not None
            and current.txid == txid
            and current.status == "confirmed"
            and current.confirmed_round == confirmed_round
        ):
            return current
        if current is None:
            reason = "no longer exists"
        elif current.txid != txid:
            reason = f"now belongs to transaction {current.txid!r}"
        elif current.status == "confirmed":
            reason = f"is already confirmed in round {current.confirmed_round!r}"
        else:
            reason = f"remains in status {current.status!r}"
        raise TransferIntentPersistenceError(
            f"transfer {operation_id!r} could not confirm transaction {txid!r} "
            f"in round {confirmed_round}: intent {reason}"
        )

    def record_error(
        self,
        operation_id: str,
        txid: str,
        error: str,
    ) -> AssetTransferIntent:
        return self._update_non_terminal(
            operation_id,
            txid,
            {
                "$set": {
                    "last_error": error[:500],
                    "updated": datetime.now(UTC),
                }
            },
        )

    def _update_non_terminal(
        self,
        operation_id: str,
        txid: str,
        update: dict[str, Any],
    ) -> AssetTransferIntent:
        document = self.collection.find_one_and_update(
            {
                "id": operation_id,
                "txid": txid,
                "status": {"$ne": "confirmed"},
            },
            update,
            return_document=ReturnDocument.AFTER,
        )
        intent = self._from_document(document)
        if intent is not None:
            return intent

        current = self.get(operation_id)
        if current is not None and current.txid == txid and current.status == "confirmed":
            return current
        raise TransferIntentPersistenceError(f"transfer {operation_id!r} changed while updating transaction {txid}")

    @staticmethod
    def _from_document(
        document: dict[str, Any] | None,
    ) -> AssetTransferIntent | None:
        if document is None:
            return None
        payload = dict(document)
        payload.pop("_id", None)
        return AssetTransferIntent.from_dict(payload)
