import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bson import Decimal128
from pymongo import MongoClient
from pymongo.database import Database

from flex import sync_pools
from flex.data import asset_prices as asset_price_data
from flex.data import assets as asset_data
from flex.db.indexes import (
    create_unique_field_index_fail_closed,
    create_unique_id_index_fail_closed,
    delete_unverified_legacy_lp_prices,
)
from flex.db.lp_projection import (
    LpProjectionResult,
    MongoLpProjectionRepository,
)
from flex.db.model.blockchain import (
    TOTAL_SUPPLY_SOURCE_INDEXER,
    UINT64_MAX,
    Asset,
    SyncState,
)
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.model.priced import AssetPrice
from flex.db.sync_coordinator import (
    MongoSyncCoordinator,
    SyncCoordinatorError,
)
from flex.domain.lp_projection import lp_round_end_order
from flex.domain.pricing import MAX_OBSERVATION_CLOCK_SKEW
from flex.domain.transactions import ASSET_TRANSFER_TX

pytestmark = pytest.mark.integration


class _CoordinatedRepository(MongoLpProjectionRepository):
    """Hold stale readers until one worker persists both state and marker."""

    def __init__(
        self,
        *,
        states,
        events,
        first_read_barrier: Barrier,
        winner_committed: Event,
        wait_for_winner: bool,
    ) -> None:
        super().__init__(states=states, events=events)
        self._first_read_barrier = first_read_barrier
        self._winner_committed = winner_committed
        self._wait_for_winner = wait_for_winner
        self._first_read = True

    def _get_state(self, pool_address: str) -> LpState:
        state = super()._get_state(pool_address)
        if self._first_read:
            self._first_read = False
            self._first_read_barrier.wait(timeout=5)
            if self._wait_for_winner and not self._winner_committed.wait(timeout=5):
                raise TimeoutError("winning replay did not persist its marker")
        return state

    def _record_event(self, transaction: LpTransaction) -> None:
        super()._record_event(transaction)
        if not self._wait_for_winner:
            self._winner_committed.set()


@pytest.fixture
def mongo_database() -> Database:
    uri = os.getenv("MONGODB_TEST_URI")
    if not uri:
        pytest.skip("MONGODB_TEST_URI is not configured")

    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=2_000,
        tz_aware=True,
    )
    client.admin.command("ping")
    database_name = f"cometa_integration_{uuid4().hex}"
    database = client[database_name]
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def _state(*, reserve: int = 100) -> LpState:
    return LpState(
        id=1,
        token_id=99,
        asset1_id=7,
        asset2_id=0,
        dex_provider="tinyman",
        address="POOL",
        last_updated_round=99,
        last_event_order=lp_round_end_order(99),
        asset1_reserve_micros=reserve,
        asset2_reserve_micros=100,
        total_tokens_micros=100,
        asset1_reserve=0,
        asset2_reserve=0,
        total_tokens=0,
        token_price_algo=0,
    )


def _transaction(
    *,
    amount: int = 10,
    asa_id: int = 7,
    event_id: str = "TX@POOL",
) -> LpTransaction:
    return LpTransaction(
        id=event_id,
        pool_address="POOL",
        user_address="USER",
        asa_id=asa_id,
        delta_amount_micros=amount,
        confirmed_round=100,
        event_position=1,
    )


def _repository(
    database: Database,
    state: LpState,
) -> MongoLpProjectionRepository:
    states = database["lp_states"]
    events = database["lp_transactions"]
    states.create_index("token_id", unique=True)
    states.create_index("address", unique=True)
    events.create_index("id", unique=True)
    states.insert_one(state.to_dict())
    return MongoLpProjectionRepository(
        states=states,
        events=events,
    )


def test_concurrent_lp_replay_applies_real_mongo_delta_once(
    mongo_database: Database,
) -> None:
    repository = _repository(mongo_database, _state())
    transaction = _transaction()
    first_read_barrier = Barrier(8)
    winner_committed = Event()
    workers = [
        _CoordinatedRepository(
            states=repository.states,
            events=repository.events,
            first_read_barrier=first_read_barrier,
            winner_committed=winner_committed,
            wait_for_winner=index != 0,
        )
        for index in range(8)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker.project, transaction) for worker in workers]
        outcomes = [future.result(timeout=10) for future in futures]

    persisted = repository.get_state("POOL")
    assert persisted.asset1_reserve_micros == 110
    assert mongo_database["lp_transactions"].count_documents({}) == 1
    assert sum(outcome.result is LpProjectionResult.APPLIED for outcome in outcomes) == 1


def test_real_mongo_repairs_marker_gap_without_repeating_delta(
    mongo_database: Database,
) -> None:
    state = _state()
    repository = _repository(mongo_database, state)
    transaction = _transaction()
    mongo_database["lp_states"].update_one(
        {"address": state.address},
        {
            "$inc": {
                "asset1_reserve_micros": Decimal128("10"),
            },
            "$set": {
                "last_event_order": transaction.event_order,
                "last_updated_round": Decimal128("100"),
            },
        },
    )

    outcome = repository.project(transaction)

    assert outcome.result is LpProjectionResult.ALREADY_APPLIED
    assert outcome.state.asset1_reserve_micros == 110
    assert mongo_database["lp_transactions"].count_documents({}) == 1


def test_real_mongo_decimal128_increment_reaches_uint64_max(
    mongo_database: Database,
) -> None:
    maximum = 2**64 - 1
    repository = _repository(
        mongo_database,
        _state(reserve=1),
    )

    outcome = repository.project(
        _transaction(amount=maximum - 1),
    )

    raw = mongo_database["lp_states"].find_one({"address": "POOL"})
    assert outcome.state.asset1_reserve_micros == maximum
    assert raw is not None
    assert raw["asset1_reserve_micros"] == Decimal128(str(maximum))


def test_real_mongo_projects_token_pool_fee_to_operational_algo(
    mongo_database: Database,
) -> None:
    state = _state()
    state.asset2_id = 8
    state.operational_algo_balance_micros = 1_000
    repository = _repository(mongo_database, state)

    outcome = repository.project(
        _transaction(
            amount=-1_000,
            asa_id=0,
            event_id="TX#fee@POOL",
        ),
    )

    raw = mongo_database["lp_states"].find_one({"address": "POOL"})
    assert outcome.state.asset1_reserve_micros == 100
    assert outcome.state.asset2_reserve_micros == 100
    assert outcome.state.operational_algo_balance_micros == 0
    assert raw is not None
    assert raw["operational_algo_balance_micros"] == Decimal128("0")


def test_real_mongo_replays_amount_and_fee_from_one_raw_transaction(
    mongo_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.asset2_id = 8
    state.operational_algo_balance_micros = 2_000
    repository = _repository(mongo_database, state)
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 8, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 100,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "USER",
        },
    }

    transactions = asyncio.run(sync_pools.process_lp_transactions([raw_transaction]))
    ordered = sorted(transactions, key=lambda transaction: transaction.event_order)
    first_outcomes = [repository.project(transaction) for transaction in ordered]
    replay_outcomes = [repository.project(transaction) for transaction in ordered]

    persisted = repository.get_state("POOL")
    assert [transaction.id for transaction in transactions] == [
        "TX@POOL",
        "TX#fee@POOL",
    ]
    assert persisted.asset1_reserve_micros == 95
    assert persisted.asset2_reserve_micros == 100
    assert persisted.operational_algo_balance_micros == 1_000
    assert persisted.last_event_order == max(transaction.event_order for transaction in transactions)
    assert mongo_database["lp_transactions"].count_documents({}) == 2
    assert all(outcome.result is LpProjectionResult.APPLIED for outcome in first_outcomes)
    assert all(outcome.result is LpProjectionResult.ALREADY_APPLIED for outcome in replay_outcomes)


def test_real_mongo_promotes_legacy_int64_balance_to_decimal128(
    mongo_database: Database,
) -> None:
    state = _state()
    payload = state.to_dict()
    for field_name in (
        "id",
        "token_id",
        "asset1_id",
        "asset2_id",
        "last_updated_round",
        "asset1_reserve_micros",
        "asset2_reserve_micros",
        "total_tokens_micros",
        "operational_algo_balance_micros",
    ):
        payload[field_name] = int(payload[field_name].to_decimal())

    states = mongo_database["lp_states"]
    events = mongo_database["lp_transactions"]
    states.create_index("token_id", unique=True)
    states.create_index("address", unique=True)
    events.create_index("id", unique=True)
    states.insert_one(payload)
    repository = MongoLpProjectionRepository(states=states, events=events)

    outcome = repository.project(_transaction())

    raw = states.find_one({"address": "POOL"})
    assert outcome.state.asset1_reserve_micros == 110
    assert raw is not None
    assert raw["asset1_reserve_micros"] == Decimal128("110")


def test_duplicate_financial_business_key_fails_without_deletion(
    mongo_database: Database,
) -> None:
    collection = mongo_database["lp_states"]
    collection.insert_many(
        [
            {"id": "a", "token_id": Decimal128("99")},
            {"id": "b", "token_id": Decimal128("99")},
        ]
    )

    with pytest.raises(RuntimeError, match="duplicate"):
        create_unique_field_index_fail_closed(
            collection,
            collection_name="lp_states",
            field_name="token_id",
            index_name="token_id_unique",
        )

    assert collection.count_documents({}) == 2


def test_duplicate_asset_identity_fails_without_deletion(
    mongo_database: Database,
) -> None:
    collection = mongo_database["assets"]
    collection.insert_many(
        [
            {"id": Decimal128("42"), "name": "first"},
            {"id": Decimal128("42"), "name": "second"},
        ]
    )

    with pytest.raises(RuntimeError, match="duplicate immutable ID"):
        create_unique_id_index_fail_closed(
            collection,
            collection_name="assets",
        )

    assert collection.count_documents({}) == 2


def test_real_mongo_deletes_only_retired_lp_price_projections(
    mongo_database: Database,
) -> None:
    collection = mongo_database["asset_prices"]
    collection.insert_many(
        [
            {"id": Decimal128("1"), "source": "vestige"},
            {"id": Decimal128("2"), "source": "vestige", "tinyman_algo_pool_id": None},
            {
                "id": Decimal128("3"),
                "source": "tinyman",
                "tinyman_algo_pool_id": Decimal128("99"),
            },
        ]
    )

    removed = delete_unverified_legacy_lp_prices(
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            )
        )
    )

    assert removed == 1
    assert {document["id"].to_decimal() for document in collection.find({}, projection={"id": 1})} == {1, 2}


def test_valid_price_replaces_far_future_observation(
    mongo_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = mongo_database["asset_prices"]
    collection.create_index("id", unique=True)
    now = datetime.now(UTC)
    collection.insert_one(
        {
            "id": Decimal128("42"),
            "name": "poisoned",
            "price_algo": 999.0,
            "price_usd": 999.0,
            "last_update_round": Decimal128("1"),
            "source": "vestige",
            "observed_at": now + MAX_OBSERVATION_CLOCK_SKEW + timedelta(days=1),
            "created": now,
            "updated": now,
        }
    )
    monkeypatch.setattr(
        asset_price_data,
        "db",
        SimpleNamespace(
            asset_prices=SimpleNamespace(
                mongodb_collection=collection,
            )
        ),
    )
    candidate = AssetPrice(
        id=42,
        name="verified",
        price_algo=0.25,
        price_usd=1.0,
        last_update_round=2,
        source="vestige",
        observed_at=now,
    )

    assert asset_price_data._upsert_asset_price(candidate) is True

    stored = collection.find_one({"id": Decimal128("42")})
    assert stored is not None
    assert stored["name"] == "verified"
    assert abs(stored["observed_at"] - now) < timedelta(milliseconds=1)


@pytest.mark.asyncio
async def test_concurrent_real_mongo_supply_migration_persists_provenance_once(
    mongo_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = mongo_database["assets"]
    inserted = collection.insert_one(
        {
            "id": Decimal128("42"),
            "total_supply": float(UINT64_MAX),
            "total_supply_micros": str(2**53),
        }
    )
    legacy_document = collection.find_one({"_id": inserted.inserted_id})
    assert legacy_document is not None
    monkeypatch.setattr(
        asset_data,
        "db",
        SimpleNamespace(
            assets=SimpleNamespace(
                mongodb_collection=collection,
            )
        ),
    )
    authoritative = Asset(
        id=42,
        name="Canonical Asset",
        decimals=0,
        unit_name="CANON",
        creator="CREATOR",
        reserve="RESERVE",
        total_supply=0,
        total_supply_micros=UINT64_MAX,
        total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
    )

    async def fetch_asset(asset_id: int) -> Asset:
        assert asset_id == 42
        await asyncio.sleep(0)
        return authoritative

    monkeypatch.setattr(asset_data, "fetch_asset", fetch_asset)

    results = await asyncio.gather(*(asset_data._backfill_canonical_supply(42, legacy_document) for _ in range(8)))

    persisted = collection.find_one({"_id": inserted.inserted_id})
    assert results == [UINT64_MAX] * 8
    assert persisted is not None
    assert persisted["total_supply_micros"] == str(UINT64_MAX)
    assert persisted["total_supply_source"] == TOTAL_SUPPLY_SOURCE_INDEXER


def test_expired_real_mongo_sync_lease_fences_stale_owner(
    mongo_database: Database,
) -> None:
    collection = mongo_database["sync_states"]
    collection.create_index("id", unique=True)
    collection.insert_one(SyncState(last_round=99).to_dict())
    coordinator = MongoSyncCoordinator(
        collection=collection,
        lease_duration=timedelta(seconds=30),
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert (
        coordinator.claim_round(
            owner="worker-a",
            expected_last_round=99,
            round_number=100,
            now=now,
        )
        is not None
    )
    assert (
        coordinator.claim_round(
            owner="worker-b",
            expected_last_round=99,
            round_number=100,
            now=now + timedelta(seconds=31),
        )
        is not None
    )

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


def test_expired_real_mongo_sync_lease_cannot_commit_without_takeover(
    mongo_database: Database,
) -> None:
    collection = mongo_database["sync_states"]
    collection.create_index("id", unique=True)
    collection.insert_one(SyncState(last_round=99).to_dict())
    coordinator = MongoSyncCoordinator(
        collection=collection,
        lease_duration=timedelta(seconds=30),
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert (
        coordinator.claim_round(
            owner="worker-a",
            expected_last_round=99,
            round_number=100,
            now=now,
        )
        is not None
    )

    with pytest.raises(SyncCoordinatorError, match="lost its claim"):
        coordinator.complete_round(
            owner="worker-a",
            expected_last_round=99,
            round_number=100,
            now=now + timedelta(seconds=31),
        )

    persisted_document = collection.find_one({"id": "main"})
    assert persisted_document is not None
    persisted_document.pop("_id")
    persisted = SyncState.from_dict(persisted_document)
    assert persisted.last_round == 99
