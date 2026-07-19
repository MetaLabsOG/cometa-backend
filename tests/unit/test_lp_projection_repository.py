from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bson import BSON, Decimal128

from flex.db.lp_projection import (
    LpProjectionPersistenceError,
    LpProjectionResult,
    MongoLpProjectionRepository,
)
from flex.db.model.blockchain import SyncState
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.sync_coordinator import (
    MongoSyncCoordinator,
    SyncCoordinatorError,
)
from flex.domain.lp_projection import lp_event_order, lp_round_end_order


def _numeric(value):
    return value.to_decimal() if isinstance(value, Decimal128) else value


def _matches(document: dict, query: dict) -> bool:
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue
        if isinstance(expected, dict):
            if "$exists" in expected:
                if (field in document) is not expected["$exists"]:
                    return False
                continue
            actual = _numeric(document.get(field))
            if "$gte" in expected and actual < _numeric(expected["$gte"]):
                return False
            if "$lte" in expected and actual > _numeric(expected["$lte"]):
                return False
            if "$gt" in expected and actual <= _numeric(expected["$gt"]):
                return False
            if "$lt" in expected and actual >= _numeric(expected["$lt"]):
                return False
            continue
        if document.get(field) != expected:
            return False
    return True


class AtomicCollection:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = [deepcopy(document) for document in documents or []]
        self.lock = RLock()
        self.fail_next_upsert = False

    def find_one(self, query, projection=None):
        with self.lock:
            document = next((item for item in self.documents if _matches(item, query)), None)
            if document is None:
                return None
            if projection is None:
                return deepcopy(document)
            return {
                field: deepcopy(document[field])
                for field, include in projection.items()
                if include and field in document
            }

    def find_one_and_update(
        self,
        query,
        update,
        *,
        upsert=False,
        return_document=None,
    ):
        del return_document
        with self.lock:
            document = next((item for item in self.documents if _matches(item, query)), None)
            if document is None and upsert:
                if self.fail_next_upsert:
                    self.fail_next_upsert = False
                    raise RuntimeError("injected marker failure")
                document = {
                    field: value
                    for field, value in query.items()
                    if not field.startswith("$") and not isinstance(value, dict)
                }
                document.update(deepcopy(update.get("$setOnInsert", {})))
                self.documents.append(document)
            if document is None:
                return None
            for field, value in update.get("$inc", {}).items():
                document[field] = Decimal128(_numeric(document[field]) + _numeric(value))
            document.update(deepcopy(update.get("$set", {})))
            return deepcopy(document)

    def update_one(self, query, update):
        with self.lock:
            document = next((item for item in self.documents if _matches(item, query)), None)
            if document is not None:
                document.update(deepcopy(update.get("$set", {})))
            return SimpleNamespace(matched_count=int(document is not None))


class BsonValidatingCollection(AtomicCollection):
    def find_one_and_update(self, query, update, **kwargs):
        BSON.encode(
            {
                "query": query,
                "update": update,
            }
        )
        return super().find_one_and_update(
            query,
            update,
            **kwargs,
        )


def _state(
    *,
    cursor: str | None = None,
    last_round: int = 99,
    reserve: int = 100,
) -> LpState:
    return LpState(
        id=1,
        token_id=99,
        asset1_id=7,
        asset2_id=0,
        dex_provider="tinyman",
        address="POOL",
        last_updated_round=last_round,
        last_event_order=cursor,
        asset1_reserve_micros=reserve,
        asset2_reserve_micros=100,
        total_tokens_micros=100,
        asset1_reserve=0,
        asset2_reserve=0,
        total_tokens=0,
        token_price_algo=0,
    )


def _transaction(
    event_id: str = "TX@POOL",
    *,
    asa_id: int = 7,
    amount: int = 10,
    round_number: int = 100,
    position: int = 1,
) -> LpTransaction:
    return LpTransaction(
        id=event_id,
        pool_address="POOL",
        user_address="USER",
        asa_id=asa_id,
        delta_amount_micros=amount,
        confirmed_round=round_number,
        event_position=position,
    )


def _repository(
    state: LpState,
    events: list[LpTransaction] | None = None,
) -> tuple[MongoLpProjectionRepository, AtomicCollection, AtomicCollection]:
    states = AtomicCollection([state.to_dict()])
    markers = AtomicCollection([event.to_dict() for event in events or []])
    return (
        MongoLpProjectionRepository(
            states=states,  # type: ignore[arg-type]
            events=markers,  # type: ignore[arg-type]
        ),
        states,
        markers,
    )


def test_crash_after_state_cas_repairs_marker_without_reapplying_delta() -> None:
    transaction = _transaction()
    repository, states, markers = _repository(
        _state(cursor=lp_round_end_order(99)),
    )
    markers.fail_next_upsert = True

    with pytest.raises(RuntimeError, match="injected marker"):
        repository.project(transaction)

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 110
    assert markers.documents == []

    replay = repository.project(transaction)

    assert replay.result is LpProjectionResult.ALREADY_APPLIED
    assert replay.state.asset1_reserve_micros == 110
    assert len(markers.documents) == 1


def test_concurrent_replay_changes_the_balance_once() -> None:
    transaction = _transaction()
    repository, states, markers = _repository(
        _state(cursor=lp_round_end_order(99)),
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(repository.project, [transaction] * 20))

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 110
    assert len(markers.documents) == 1
    assert sum(outcome.result is LpProjectionResult.APPLIED for outcome in outcomes) == 1


def test_replay_refreshes_stale_state_before_declaring_marker_divergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = _transaction()
    stale_state = _state(cursor=lp_round_end_order(99))
    repository, _, _ = _repository(
        _state(
            cursor=transaction.event_order,
            last_round=100,
            reserve=110,
        ),
        events=[transaction],
    )
    original_get_state = MongoLpProjectionRepository._get_state
    read_count = 0

    def stale_then_current(
        current_repository: MongoLpProjectionRepository,
        pool_address: str,
    ) -> LpState:
        nonlocal read_count
        read_count += 1
        if read_count == 1:
            return stale_state
        return original_get_state(current_repository, pool_address)

    monkeypatch.setattr(
        MongoLpProjectionRepository,
        "_get_state",
        stale_then_current,
    )

    outcome = repository.project(transaction)

    assert outcome.result is LpProjectionResult.ALREADY_APPLIED
    assert outcome.state.asset1_reserve_micros == 110
    assert read_count == 2


def test_later_event_cannot_hide_an_unrecorded_earlier_event() -> None:
    later = _transaction("Z@POOL", position=2)
    earlier = _transaction("A@POOL", position=1)
    repository, states, _ = _repository(
        _state(cursor=lp_round_end_order(99)),
    )

    repository.project(later)

    with pytest.raises(LpProjectionPersistenceError, match="advanced past"):
        repository.project(earlier)

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 110


def test_snapshot_cursor_covers_legacy_events_without_guessing_markers() -> None:
    transaction = _transaction(round_number=100)
    repository, states, markers = _repository(
        _state(cursor=lp_round_end_order(100), last_round=100),
    )

    outcome = repository.project(transaction)

    assert outcome.result is LpProjectionResult.SNAPSHOT_COVERED
    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 100
    assert markers.documents == []


def test_legacy_state_without_cutover_snapshot_fails_closed() -> None:
    repository, states, markers = _repository(
        _state(cursor=None, last_round=100),
    )

    with pytest.raises(LpProjectionPersistenceError, match="authoritative snapshot"):
        repository.project(_transaction(round_number=101))

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 100
    assert markers.documents == []


def test_projection_rejects_underflow_and_preserves_cursor() -> None:
    initial_cursor = lp_round_end_order(99)
    transaction = _transaction(amount=-101)
    repository, states, _ = _repository(
        _state(cursor=initial_cursor),
    )

    with pytest.raises(LpProjectionPersistenceError, match="underflow or overflow"):
        repository.project(transaction)

    stored = LpState.from_dict(states.documents[0])
    assert stored.asset1_reserve_micros == 100
    assert stored.last_event_order == initial_cursor


def test_existing_event_id_with_different_payload_fails_closed() -> None:
    expected = _transaction(amount=10)
    conflicting = _transaction(amount=11)
    repository, states, _ = _repository(
        _state(cursor=lp_round_end_order(99)),
        events=[conflicting],
    )

    with pytest.raises(LpProjectionPersistenceError, match="different immutable data"):
        repository.project(expected)

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 100


def test_existing_marker_cannot_advance_a_state_without_its_delta() -> None:
    transaction = _transaction()
    initial_cursor = lp_round_end_order(99)
    repository, states, _ = _repository(
        _state(cursor=initial_cursor),
        events=[transaction],
    )

    with pytest.raises(
        LpProjectionPersistenceError,
        match="recorded but state",
    ):
        repository.project(transaction)

    stored = LpState.from_dict(states.documents[0])
    assert stored.asset1_reserve_micros == 100
    assert stored.last_event_order == initial_cursor


def test_uint64_amounts_use_decimal128_without_precision_loss() -> None:
    amount = 2**64 - 2
    repository, states, _ = _repository(
        _state(
            cursor=lp_round_end_order(99),
            reserve=1,
        ),
    )

    outcome = repository.project(
        _transaction(amount=amount),
    )

    assert outcome.state.asset1_reserve_micros == 2**64 - 1
    assert isinstance(states.documents[0]["asset1_reserve_micros"], Decimal128)
    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 2**64 - 1


def test_uint64_identifiers_and_cursors_are_bson_safe() -> None:
    maximum = 2**64 - 1
    transaction = LpTransaction(
        id="TX@POOL",
        pool_address="POOL",
        user_address="USER",
        asa_id=maximum,
        delta_amount_micros=maximum,
        confirmed_round=maximum,
        event_position=maximum,
    )

    encoded = BSON.encode(transaction.to_dict())
    restored = LpTransaction.from_dict(BSON(encoded).decode())

    assert restored.asa_id == maximum
    assert restored.delta_amount_micros == maximum
    assert restored.confirmed_round == maximum
    assert restored.event_position == maximum


def test_operational_algo_balance_is_bson_safe_and_backward_compatible() -> None:
    maximum = 2**64 - 1
    state = _state()
    state.operational_algo_balance_micros = maximum

    encoded = BSON.encode(state.to_dict())
    restored = LpState.from_dict(BSON(encoded).decode())

    assert restored.operational_algo_balance_micros == maximum

    legacy_payload = state.to_dict()
    legacy_payload.pop("operational_algo_balance_micros")
    restored_legacy = LpState.from_dict(legacy_payload)

    assert restored_legacy.operational_algo_balance_micros == 0


def test_uint64_repository_queries_and_updates_are_bson_safe() -> None:
    maximum = 2**64 - 1
    state = _state(
        cursor=lp_round_end_order(maximum - 1),
        last_round=maximum - 1,
    )
    state.token_id = maximum
    states = BsonValidatingCollection([state.to_dict()])
    markers = BsonValidatingCollection()
    repository = MongoLpProjectionRepository(
        states=states,  # type: ignore[arg-type]
        events=markers,  # type: ignore[arg-type]
    )

    outcome = repository.project(
        _transaction(
            amount=1,
            round_number=maximum,
            position=maximum,
        ),
    )

    assert outcome.result is LpProjectionResult.APPLIED
    assert outcome.state.last_updated_round == maximum
    BSON.encode(
        LpState.encode_query(
            {
                "token_id": {
                    "$in": [maximum],
                }
            }
        )
    )


def test_token_token_pool_fee_updates_only_operational_algo_balance() -> None:
    state = _state(
        cursor=lp_round_end_order(99),
        reserve=100,
    )
    state.asset2_id = 8
    state.asset2_reserve_micros = 200
    state.operational_algo_balance_micros = 5_000
    repository, states, _ = _repository(state)

    outcome = repository.project(
        _transaction(
            event_id="TX#fee@POOL",
            asa_id=0,
            amount=-1_000,
        ),
    )

    assert outcome.result is LpProjectionResult.APPLIED
    assert outcome.state.asset1_reserve_micros == 100
    assert outcome.state.asset2_reserve_micros == 200
    assert outcome.state.operational_algo_balance_micros == 4_000
    persisted = LpState.from_dict(states.documents[0])
    assert persisted.operational_algo_balance_micros == 4_000
    assert isinstance(
        states.documents[0]["operational_algo_balance_micros"],
        Decimal128,
    )


def test_event_position_is_sorted_numerically_within_a_round() -> None:
    assert lp_event_order(100, "TX-2", 2) < lp_event_order(100, "TX-10", 10)


def test_snapshot_cannot_overwrite_a_newer_event_cursor() -> None:
    newer_cursor = lp_event_order(101, "TX@POOL", 1)
    repository, states, _ = _repository(
        _state(cursor=newer_cursor, last_round=101, reserve=150),
    )

    result = repository.replace_snapshot(
        _state(cursor=None, last_round=100, reserve=90),
        observed_round=100,
    )

    assert result.last_event_order == newer_cursor
    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 150


def test_balance_snapshot_does_not_publish_derived_price_fields() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    current = _state(
        cursor=lp_round_end_order(100),
        last_round=100,
        reserve=100,
    )
    current.asset1_reserve = 1.0
    current.asset2_reserve = 2.0
    current.total_tokens = 3.0
    current.token_price_algo = 4.0
    current.derived_observed_at = observed_at
    current.asset2_id = 8
    current.operational_algo_balance_micros = 5_000
    repository, states, _ = _repository(current)

    incoming = _state(cursor=None, last_round=101, reserve=150)
    incoming.asset1_reserve = 10.0
    incoming.asset2_reserve = 20.0
    incoming.total_tokens = 30.0
    incoming.token_price_algo = 40.0
    incoming.derived_observed_at = observed_at + timedelta(minutes=1)
    incoming.asset2_id = 8
    incoming.operational_algo_balance_micros = 6_000

    result = repository.replace_snapshot(
        incoming,
        observed_round=101,
    )

    assert result.asset1_reserve_micros == 150
    assert result.operational_algo_balance_micros == 6_000
    assert result.asset1_reserve == 1.0
    assert result.asset2_reserve == 2.0
    assert result.total_tokens == 3.0
    assert result.token_price_algo == 4.0
    assert result.derived_observed_at == observed_at
    persisted = LpState.from_dict(states.documents[0])
    assert persisted.token_price_algo == 4.0
    assert persisted.derived_observed_at == observed_at


def test_same_round_snapshot_with_different_balances_fails_closed() -> None:
    snapshot_cursor = lp_round_end_order(100)
    repository, states, _ = _repository(
        _state(cursor=snapshot_cursor, last_round=100, reserve=100),
    )

    with pytest.raises(LpProjectionPersistenceError, match="conflicts"):
        repository.replace_snapshot(
            _state(cursor=None, last_round=100, reserve=101),
            observed_round=100,
        )

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 100


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("asset1_reserve_micros", -1),
        ("asset2_reserve_micros", True),
        ("total_tokens_micros", 2**64),
        ("operational_algo_balance_micros", 1.5),
    ],
)
def test_invalid_snapshot_is_rejected_before_mongo_write(
    field_name: str,
    invalid_value: object,
) -> None:
    state = _state(cursor=None)
    setattr(state, field_name, invalid_value)
    states = SimpleNamespace(
        find_one_and_update=Mock(),
    )
    repository = MongoLpProjectionRepository(
        states=states,  # type: ignore[arg-type]
        events=AtomicCollection(),  # type: ignore[arg-type]
    )

    with pytest.raises(LpProjectionPersistenceError, match=field_name):
        repository.replace_snapshot(state, observed_round=100)

    states.find_one_and_update.assert_not_called()


def test_event_marker_counterparty_is_immutable() -> None:
    expected = _transaction()
    conflicting = _transaction()
    conflicting.user_address = "OTHER-USER"
    repository, states, _ = _repository(
        _state(cursor=lp_round_end_order(99)),
        events=[conflicting],
    )

    with pytest.raises(LpProjectionPersistenceError, match="immutable data"):
        repository.project(expected)

    assert LpState.from_dict(states.documents[0]).asset1_reserve_micros == 100


def test_expired_round_lease_uses_fencing_owner_and_checkpoint_cas() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    collection = AtomicCollection(
        [
            SyncState(
                last_round=99,
            ).to_dict()
        ]
    )
    coordinator = MongoSyncCoordinator(
        collection=collection,  # type: ignore[arg-type]
        lease_duration=timedelta(seconds=30),
    )

    first = coordinator.claim_round(
        owner="worker-a",
        expected_last_round=99,
        round_number=100,
        now=now,
    )
    blocked = coordinator.claim_round(
        owner="worker-b",
        expected_last_round=99,
        round_number=100,
        now=now + timedelta(seconds=1),
    )
    takeover = coordinator.claim_round(
        owner="worker-b",
        expected_last_round=99,
        round_number=100,
        now=now + timedelta(seconds=31),
    )

    assert first is not None
    assert blocked is None
    assert takeover is not None
    with pytest.raises(SyncCoordinatorError, match="lost its claim"):
        coordinator.complete_round(
            owner="worker-a",
            expected_last_round=99,
            round_number=100,
            now=now + timedelta(seconds=32),
        )

    completed = coordinator.complete_round(
        owner="worker-b",
        expected_last_round=99,
        round_number=100,
        now=now + timedelta(seconds=32),
    )

    assert completed.last_round == 100


def test_expired_round_lease_cannot_complete_without_takeover() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    collection = AtomicCollection([SyncState(last_round=99).to_dict()])
    coordinator = MongoSyncCoordinator(
        collection=collection,  # type: ignore[arg-type]
        lease_duration=timedelta(seconds=30),
    )

    claimed = coordinator.claim_round(
        owner="worker-a",
        expected_last_round=99,
        round_number=100,
        now=now,
    )

    assert claimed is not None
    with pytest.raises(SyncCoordinatorError, match="lost its claim"):
        coordinator.complete_round(
            owner="worker-a",
            expected_last_round=99,
            round_number=100,
            now=now + timedelta(seconds=31),
        )
    assert SyncState.from_dict(collection.documents[0]).last_round == 99


def test_uint64_sync_checkpoint_operations_are_bson_safe() -> None:
    maximum = 2**64 - 1
    now = datetime(2026, 1, 1, tzinfo=UTC)
    collection = BsonValidatingCollection(
        [
            SyncState(
                last_round=maximum - 1,
            ).to_dict()
        ]
    )
    coordinator = MongoSyncCoordinator(
        collection=collection,  # type: ignore[arg-type]
    )

    claimed = coordinator.claim_round(
        owner="worker",
        expected_last_round=maximum - 1,
        round_number=maximum,
        now=now,
    )
    completed = coordinator.complete_round(
        owner="worker",
        expected_last_round=maximum - 1,
        round_number=maximum,
        now=now,
    )

    assert claimed is not None
    assert claimed.claimed_round == maximum
    assert completed.last_round == maximum
