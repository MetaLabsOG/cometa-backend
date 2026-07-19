"""Atomic MongoDB adapter for liquidity-pool event projection."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from flex.db.bson import encode_bson_integer
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.domain.lp_projection import (
    MAX_ALGORAND_UINT,
    LpBalanceDelta,
    lp_balance_delta,
    lp_round_end_order,
    snapshot_covers_event,
)
from flex.domain.transactions import event_id_aliases


class LpProjectionPersistenceError(RuntimeError):
    """Raised when replay cannot prove a safe LP projection outcome."""


class LpProjectionResult(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    SNAPSHOT_COVERED = "snapshot_covered"


@dataclass(frozen=True, slots=True)
class LpProjectionOutcome:
    state: LpState
    result: LpProjectionResult

    @property
    def changed_balances(self) -> bool:
        return self.result is LpProjectionResult.APPLIED

    @property
    def requires_derived_refresh(self) -> bool:
        return self.result is not LpProjectionResult.SNAPSHOT_COVERED


@dataclass(slots=True)
class MongoLpProjectionRepository:
    states: Collection[dict[str, Any]]
    events: Collection[dict[str, Any]]

    def project(self, transaction: LpTransaction) -> LpProjectionOutcome:
        """Apply one event atomically or prove that replay is already covered."""

        while True:
            state = self._get_state(transaction.pool_address)
            order = transaction.event_order
            if order is None:
                raise LpProjectionPersistenceError("LP transaction has no deterministic event order")

            canonical_event = self.events.find_one(
                {"id": transaction.id},
            )
            if canonical_event is not None:
                self._assert_event_document(
                    canonical_event,
                    expected=transaction,
                )
            legacy_alias = self._legacy_alias(transaction)
            if legacy_alias is not None:
                raise LpProjectionPersistenceError(
                    f"legacy LP marker {legacy_alias!r} is ambiguous for {transaction.id!r}; "
                    "reconcile from an authoritative pool snapshot"
                )

            cursor = state.last_event_order
            if cursor is None:
                raise LpProjectionPersistenceError(
                    f"LP state {state.token_id} has no cutover cursor; take an authoritative snapshot before replay"
                )

            if canonical_event is not None:
                if cursor < order:
                    # Another worker may have advanced the state and recorded
                    # the marker after this worker read its initial snapshot.
                    # Re-read before classifying marker/state divergence as
                    # persistent corruption.
                    state = self._get_state(transaction.pool_address)
                    cursor = state.last_event_order
                    if cursor is None or cursor < order:
                        raise LpProjectionPersistenceError(
                            f"LP event {transaction.id!r} is recorded but state "
                            f"{state.token_id} is behind it; reconcile from an "
                            "authoritative pool snapshot"
                        )
                return LpProjectionOutcome(
                    state=state,
                    result=LpProjectionResult.ALREADY_APPLIED,
                )

            if cursor == order:
                self._record_event(transaction)
                return LpProjectionOutcome(
                    state=state,
                    result=LpProjectionResult.ALREADY_APPLIED,
                )

            if cursor > order:
                if snapshot_covers_event(
                    cursor,
                    confirmed_round=transaction.confirmed_round,
                ):
                    return LpProjectionOutcome(
                        state=state,
                        result=LpProjectionResult.SNAPSHOT_COVERED,
                    )
                raise LpProjectionPersistenceError(
                    f"LP state {state.token_id} advanced past unrecorded event {transaction.id!r}"
                )

            delta = lp_balance_delta(
                token_id=state.token_id,
                asset1_id=state.asset1_id,
                asset2_id=state.asset2_id,
                event_asset_id=transaction.asa_id,
                event_pool_delta_micros=transaction.delta_amount_micros,
            )
            updated = self._apply_delta(
                state=state,
                order=order,
                confirmed_round=transaction.confirmed_round,
                delta=delta,
            )
            if updated is None:
                latest = self._get_state(transaction.pool_address)
                if latest.last_event_order != cursor:
                    continue
                raise LpProjectionPersistenceError(
                    f"LP event {transaction.id!r} would underflow or overflow {delta.field}"
                )

            # Marker-last is intentional: if this write fails, replay observes
            # cursor == order and heals the marker without repeating the delta.
            self._record_event(transaction)
            return LpProjectionOutcome(
                state=updated,
                result=LpProjectionResult.APPLIED,
            )

    def update_derived_fields(
        self,
        state: LpState,
        *,
        expected_cursor: str,
    ) -> LpState | None:
        if state.derived_observed_at is None:
            raise LpProjectionPersistenceError("derived LP fields have no observation timestamp")
        document = self.states.find_one_and_update(
            {
                "token_id": encode_bson_integer(state.token_id),
                "last_event_order": expected_cursor,
                "$or": [
                    {"derived_observed_at": {"$exists": False}},
                    {"derived_observed_at": None},
                    {
                        "derived_observed_at": {
                            "$lte": state.derived_observed_at,
                        }
                    },
                ],
            },
            {
                "$set": {
                    "asset1_reserve": state.asset1_reserve,
                    "asset2_reserve": state.asset2_reserve,
                    "total_tokens": state.total_tokens,
                    "token_price_algo": state.token_price_algo,
                    "derived_observed_at": state.derived_observed_at,
                    "updated": datetime.now(UTC),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._from_state_document(document)

    def replace_snapshot(
        self,
        state: LpState,
        *,
        observed_round: int,
    ) -> LpState:
        """Replace balances only when the authoritative snapshot is newer."""

        snapshot_order = lp_round_end_order(observed_round)
        document = self.states.find_one_and_update(
            {
                "token_id": encode_bson_integer(state.token_id),
                "$or": [
                    {"last_event_order": {"$exists": False}},
                    {"last_event_order": None},
                    {"last_event_order": {"$lt": snapshot_order}},
                ],
            },
            {
                "$set": {
                    "asset1_reserve_micros": encode_bson_integer(
                        state.asset1_reserve_micros,
                    ),
                    "asset2_reserve_micros": encode_bson_integer(
                        state.asset2_reserve_micros,
                    ),
                    "total_tokens_micros": encode_bson_integer(
                        state.total_tokens_micros,
                    ),
                    "asset1_reserve": state.asset1_reserve,
                    "asset2_reserve": state.asset2_reserve,
                    "total_tokens": state.total_tokens,
                    "token_price_algo": state.token_price_algo,
                    "derived_observed_at": state.derived_observed_at,
                    "last_updated_round": encode_bson_integer(
                        observed_round,
                    ),
                    "last_event_order": snapshot_order,
                    "updated": datetime.now(UTC),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        replaced = self._from_state_document(document)
        if replaced is not None:
            return replaced

        current = self._get_state(state.address)
        if current.last_event_order == snapshot_order and self._balances(current) != self._balances(state):
            raise LpProjectionPersistenceError(
                f"LP snapshot {snapshot_order} conflicts with persisted balances for token {state.token_id}"
            )
        return current

    def get_state(self, pool_address: str) -> LpState:
        return self._get_state(pool_address)

    def _get_state(self, pool_address: str) -> LpState:
        document = self.states.find_one({"address": pool_address})
        state = self._from_state_document(document)
        if state is None:
            raise LpProjectionPersistenceError(f"LP state not found for address {pool_address}")
        return state

    def _apply_delta(
        self,
        *,
        state: LpState,
        order: str,
        confirmed_round: int,
        delta: LpBalanceDelta,
    ) -> LpState | None:
        bounds: dict[str, Any] = {
            "$gte": encode_bson_integer(max(0, -delta.amount)),
        }
        if delta.amount > 0:
            bounds["$lte"] = encode_bson_integer(
                MAX_ALGORAND_UINT - delta.amount,
            )
        document = self.states.find_one_and_update(
            {
                "token_id": encode_bson_integer(state.token_id),
                "last_event_order": state.last_event_order,
                delta.field: bounds,
            },
            {
                "$inc": {
                    delta.field: encode_bson_integer(delta.amount),
                },
                "$set": {
                    "last_event_order": order,
                    "last_updated_round": encode_bson_integer(
                        confirmed_round,
                    ),
                    "updated": datetime.now(UTC),
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._from_state_document(document)

    def _record_event(self, transaction: LpTransaction) -> None:
        payload = transaction.to_dict()
        try:
            document = self.events.find_one_and_update(
                {"id": transaction.id},
                {"$setOnInsert": payload},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            document = self.events.find_one({"id": transaction.id})
        if document is None:
            raise LpProjectionPersistenceError(f"failed to record LP event {transaction.id!r}")
        self._assert_event_document(
            document,
            expected=transaction,
        )

    @staticmethod
    def _assert_event_document(
        document: dict[str, Any],
        *,
        expected: LpTransaction,
    ) -> None:
        persisted = dict(document)
        persisted.pop("_id", None)
        persisted_event = LpTransaction.from_dict(persisted)
        if (
            persisted_event.pool_address,
            persisted_event.asa_id,
            persisted_event.delta_amount_micros,
            persisted_event.confirmed_round,
            persisted_event.event_position,
            persisted_event.event_order,
        ) != (
            expected.pool_address,
            expected.asa_id,
            expected.delta_amount_micros,
            expected.confirmed_round,
            expected.event_position,
            expected.event_order,
        ):
            raise LpProjectionPersistenceError(f"LP event ID {expected.id!r} belongs to different immutable data")

    def _legacy_alias(self, transaction: LpTransaction) -> str | None:
        aliases = event_id_aliases(transaction.id)
        for alias in aliases:
            if alias == transaction.id:
                continue
            if self.events.find_one({"id": alias}, projection={"_id": 1}) is not None:
                return alias
        return None

    @staticmethod
    def _balances(state: LpState) -> tuple[int, int, int]:
        return (
            state.asset1_reserve_micros,
            state.asset2_reserve_micros,
            state.total_tokens_micros,
        )

    @staticmethod
    def _from_state_document(document: dict[str, Any] | None) -> LpState | None:
        if document is None:
            return None
        payload = dict(document)
        payload.pop("_id", None)
        return cast(
            LpState,
            LpState.from_dict(payload),
        )
