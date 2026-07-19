"""Mongo-backed single-writer ordering gate for the block projector."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pymongo import ReturnDocument
from pymongo.collection import Collection

from flex.db.bson import encode_bson_integer
from flex.db.model.blockchain import SyncState

SYNC_STATE_ID = "main"


class SyncCoordinatorError(RuntimeError):
    """Raised when a worker loses ownership of a claimed round."""


@dataclass(slots=True)
class MongoSyncCoordinator:
    collection: Collection[dict[str, Any]]
    lease_duration: timedelta = timedelta(minutes=2)

    def claim_round(
        self,
        *,
        owner: str,
        expected_last_round: int | None,
        round_number: int,
        now: datetime | None = None,
    ) -> SyncState | None:
        self._validate_next_round(
            expected_last_round=expected_last_round,
            round_number=round_number,
        )
        current_time = now or datetime.now(UTC)
        encoded_expected_round = None if expected_last_round is None else encode_bson_integer(expected_last_round)
        document = self.collection.find_one_and_update(
            {
                "id": SYNC_STATE_ID,
                "last_round": encoded_expected_round,
                "$or": [
                    {"lease_until": {"$exists": False}},
                    {"lease_until": None},
                    {"lease_until": {"$lte": current_time}},
                    {"lease_owner": owner},
                ],
            },
            {
                "$set": {
                    "claimed_round": encode_bson_integer(round_number),
                    "lease_owner": owner,
                    "lease_until": current_time + self.lease_duration,
                    "last_error": None,
                    "updated": current_time,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._from_document(document)

    def complete_round(
        self,
        *,
        owner: str,
        expected_last_round: int | None,
        round_number: int,
        now: datetime | None = None,
    ) -> SyncState:
        self._validate_next_round(
            expected_last_round=expected_last_round,
            round_number=round_number,
        )
        current_time = now or datetime.now(UTC)
        encoded_expected_round = None if expected_last_round is None else encode_bson_integer(expected_last_round)
        document = self.collection.find_one_and_update(
            {
                "id": SYNC_STATE_ID,
                "last_round": encoded_expected_round,
                "claimed_round": encode_bson_integer(round_number),
                "lease_owner": owner,
                "lease_until": {"$gt": current_time},
            },
            {
                "$set": {
                    "last_round": encode_bson_integer(round_number),
                    "claimed_round": None,
                    "lease_owner": None,
                    "lease_until": None,
                    "last_error": None,
                    "updated": current_time,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        state = self._from_document(document)
        if state is None:
            raise SyncCoordinatorError(f"worker {owner!r} lost its claim for round {round_number}")
        return state

    def advance_snapshot(
        self,
        *,
        expected_last_round: int | None,
        round_number: int,
        now: datetime | None = None,
    ) -> SyncState:
        if (
            isinstance(round_number, bool)
            or not isinstance(round_number, int)
            or round_number < 0
            or (expected_last_round is not None and round_number < expected_last_round)
        ):
            raise SyncCoordinatorError("snapshot checkpoint cannot regress")
        current_time = now or datetime.now(UTC)
        encoded_expected_round = None if expected_last_round is None else encode_bson_integer(expected_last_round)
        document = self.collection.find_one_and_update(
            {
                "id": SYNC_STATE_ID,
                "last_round": encoded_expected_round,
                "$or": [
                    {"lease_until": {"$exists": False}},
                    {"lease_until": None},
                    {"lease_until": {"$lte": current_time}},
                ],
            },
            {
                "$set": {
                    "last_round": encode_bson_integer(round_number),
                    "claimed_round": None,
                    "lease_owner": None,
                    "lease_until": None,
                    "last_error": None,
                    "updated": current_time,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        state = self._from_document(document)
        if state is None:
            raise SyncCoordinatorError("sync checkpoint changed during authoritative snapshot")
        return state

    def release_after_error(
        self,
        *,
        owner: str,
        round_number: int,
        error: str,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(UTC)
        self.collection.update_one(
            {
                "id": SYNC_STATE_ID,
                "claimed_round": encode_bson_integer(round_number),
                "lease_owner": owner,
            },
            {
                "$set": {
                    "claimed_round": None,
                    "lease_owner": None,
                    "lease_until": None,
                    "last_error": error[:500],
                    "updated": current_time,
                }
            },
        )

    @staticmethod
    def _from_document(document: dict[str, Any] | None) -> SyncState | None:
        if document is None:
            return None
        payload = dict(document)
        payload.pop("_id", None)
        return cast(
            SyncState,
            SyncState.from_dict(payload),
        )

    @staticmethod
    def _validate_next_round(
        *,
        expected_last_round: int | None,
        round_number: int,
    ) -> None:
        if (
            isinstance(round_number, bool)
            or not isinstance(round_number, int)
            or round_number < 0
            or (expected_last_round is not None and round_number != expected_last_round + 1)
        ):
            raise SyncCoordinatorError("projected rounds must advance exactly once")
