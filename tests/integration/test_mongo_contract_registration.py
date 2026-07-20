import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from pymongo import MongoClient

import app as api_module
from core.db.contracts import (
    ensure_contract_id_index,
    get_or_create_contract,
)
from core.db.model import ContractInfo
from flex.application import pool_registration
from flex.application.pool_registration import PoolIdentityConflictError
from flex.data import pool_state as pool_state_data
from flex.data.pool_state import PoolStateIdentityConflictError
from flex.db.cometa_database import CometaDatabase
from flex.db.indexes import ensure_database_indexes
from flex.db.model.blockchain import AssetInfo
from flex.db.model.pool_states import PoolState
from flex.db.model.pools import PoolType, StakingPool

pytestmark = pytest.mark.integration


@pytest.fixture
def registration_databases():
    uri = os.getenv("MONGODB_TEST_URI")
    if not uri:
        pytest.skip("MONGODB_TEST_URI is not configured")

    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=2_000,
        tz_aware=True,
    )
    client.admin.command("ping")
    suffix = uuid4().hex
    legacy_database = client[f"cometa_contracts_{suffix}"]
    flex_database = client[f"cometa_flex_{suffix}"]
    try:
        yield legacy_database, CometaDatabase(flex_database)
    finally:
        client.drop_database(legacy_database.name)
        client.drop_database(flex_database.name)
        client.close()


def _registration_records() -> tuple[ContractInfo, StakingPool, PoolState]:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    asset = AssetInfo(
        id=7,
        name="Stake",
        decimals=6,
        unit_name="STK",
    )
    contract = ContractInfo(
        type="distribution",
        id=42,
        version="17.0.5",
        deployed_timestamp=timestamp.timestamp(),
        deployed_date=timestamp,
        begin_date=timestamp,
        end_date=timestamp,
        description="Concurrent registration",
        metadata={"cache": {"initial": {}}},
    )
    pool = StakingPool(
        id=contract.id,
        description=contract.description,
        address="POOL",
        stake_token=asset,
        reward_token=asset,
        reward_amount_micros=1_000,
        algo_reward_amount_micros=0,
        begin_block=10,
        end_block=20,
        lock_length_blocks=0,
        deploy_date=timestamp,
        begin_date=timestamp,
        end_date=timestamp,
    )
    state = PoolState(
        pool_id=contract.id,
        type=PoolType.STAKING,
        stake_token=asset,
        address=pool.address,
    )
    return contract, pool, state


def _persist_registration(
    *,
    legacy_contracts,
    flex_database: CometaDatabase,
    contract: ContractInfo,
    pool: StakingPool,
    state: PoolState,
) -> bool:
    contract_write = get_or_create_contract(
        contract,
        target_collection=legacy_contracts,
    )
    flex_database.staking_pools.get_or_create(pool)
    flex_database.pool_states.get_or_create_by(
        state,
        pool_id=state.pool_id,
    )
    return contract_write.created


def test_concurrent_registration_persists_one_identity_graph(
    registration_databases,
) -> None:
    legacy_database, flex_database = registration_databases
    legacy_contracts = legacy_database["contract"]
    ensure_contract_id_index(target_collection=legacy_contracts)
    ensure_database_indexes(flex_database)
    contract, pool, state = _registration_records()
    barrier = Barrier(8)

    def register() -> bool:
        barrier.wait(timeout=5)
        return _persist_registration(
            legacy_contracts=legacy_contracts,
            flex_database=flex_database,
            contract=contract,
            pool=pool,
            state=state,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = [future.result(timeout=10) for future in [executor.submit(register) for _ in range(8)]]

    assert sum(results) == 1
    assert legacy_contracts.count_documents({"id": contract.id}) == 1
    assert flex_database.staking_pools.mongodb_collection.count_documents({"id": contract.id}) == 1
    assert flex_database.pool_states.mongodb_collection.count_documents({"pool_id": contract.id}) == 1


def test_contract_index_rejects_existing_duplicate_identity(
    registration_databases,
) -> None:
    legacy_database, _ = registration_databases
    contracts = legacy_database["contract"]
    contracts.insert_many([{"id": 42}, {"id": 42}])

    with pytest.raises(RuntimeError, match="duplicate immutable ID 42"):
        ensure_contract_id_index(target_collection=contracts)


@pytest.mark.parametrize(
    ("collection_name", "field_name"),
    [
        ("staking_pools", "id"),
        ("farming_pools", "id"),
        ("pool_states", "pool_id"),
    ],
)
def test_flex_indexes_reject_existing_duplicate_identity(
    registration_databases,
    collection_name: str,
    field_name: str,
) -> None:
    _, flex_database = registration_databases
    flex_database.mongodb_database[collection_name].insert_many([{field_name: 42}, {field_name: 42}])

    with pytest.raises(RuntimeError, match="duplicate"):
        ensure_database_indexes(flex_database)


def test_flex_indexes_reject_cross_collection_pool_identity(
    registration_databases,
) -> None:
    _, flex_database = registration_databases
    flex_database.staking_pools.mongodb_collection.insert_one({"id": 42})
    flex_database.farming_pools.mongodb_collection.insert_one({"id": 42})

    with pytest.raises(RuntimeError, match="exists in both"):
        ensure_database_indexes(flex_database)


@pytest.mark.asyncio
async def test_registration_rejects_opposite_kind_orphan_without_target_write(
    registration_databases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, flex_database = registration_databases
    ensure_database_indexes(flex_database)
    contract, pool, _ = _registration_records()
    flex_database.farming_pools.mongodb_collection.insert_one({"id": contract.id})

    async def build_pool(_contract: ContractInfo, distribution: bool = False) -> StakingPool:
        assert distribution is True
        return pool

    monkeypatch.setattr(pool_registration, "db", flex_database)
    monkeypatch.setattr(
        pool_registration,
        "staking_pool_from_contract_info",
        build_pool,
    )

    with pytest.raises(PoolIdentityConflictError, match="opposite pool type"):
        await pool_registration.create_pool_from_contract(contract)

    assert flex_database.staking_pools.mongodb_collection.count_documents({"id": contract.id}) == 0


@pytest.mark.asyncio
async def test_registration_rejects_incompatible_existing_pool(
    registration_databases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, flex_database = registration_databases
    ensure_database_indexes(flex_database)
    contract, candidate, _ = _registration_records()
    flex_database.staking_pools.create(replace(candidate, address="OTHER"))

    async def build_pool(_contract: ContractInfo, distribution: bool = False) -> StakingPool:
        assert distribution is True
        return candidate

    monkeypatch.setattr(pool_registration, "db", flex_database)
    monkeypatch.setattr(
        pool_registration,
        "staking_pool_from_contract_info",
        build_pool,
    )

    with pytest.raises(PoolIdentityConflictError, match="incompatible persisted"):
        await pool_registration.create_pool_from_contract(contract)

    assert flex_database.staking_pools.mongodb_collection.count_documents({"id": contract.id}) == 1
    stored = flex_database.staking_pools.get_by_primary_key(contract.id)
    assert stored.address == "OTHER"


@pytest.mark.asyncio
async def test_pool_state_rejects_incompatible_existing_identity(
    registration_databases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, flex_database = registration_databases
    ensure_database_indexes(flex_database)
    contract, pool, candidate = _registration_records()
    flex_database.staking_pools.create(pool)
    flex_database.pool_states.create(replace(candidate, address="OTHER"))
    monkeypatch.setattr(pool_state_data, "db", flex_database)
    monkeypatch.setattr(pool_state_data, "get_contract", lambda _pool_id: contract)
    await pool_state_data.get_or_create_pool_state.cache.clear()

    with pytest.raises(PoolStateIdentityConflictError, match="incompatible persisted"):
        await pool_state_data.get_or_create_pool_state(contract.id)

    assert flex_database.pool_states.mongodb_collection.count_documents({"pool_id": contract.id}) == 1
    stored = flex_database.pool_states.get_one(pool_id=contract.id)
    assert stored.address == "OTHER"


@pytest.mark.asyncio
async def test_registration_saga_rejects_incompatible_existing_pool_state(
    registration_databases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_database, flex_database = registration_databases
    legacy_contracts = legacy_database["contract"]
    ensure_contract_id_index(target_collection=legacy_contracts)
    ensure_database_indexes(flex_database)
    contract, pool, candidate = _registration_records()
    flex_database.staking_pools.create(pool)
    flex_database.pool_states.create(replace(candidate, address="OTHER"))

    async def build_pool(_contract: ContractInfo, distribution: bool = False) -> StakingPool:
        assert distribution is True
        return pool

    monkeypatch.setattr(pool_registration, "db", flex_database)
    monkeypatch.setattr(
        pool_registration,
        "staking_pool_from_contract_info",
        build_pool,
    )
    monkeypatch.setattr(pool_state_data, "db", flex_database)
    monkeypatch.setattr(
        api_module,
        "get_or_create_contract",
        lambda requested: get_or_create_contract(
            requested,
            target_collection=legacy_contracts,
        ),
    )
    monkeypatch.setattr(api_module, "invalidate_contracts_cache", lambda: None)
    monkeypatch.setattr(
        api_module,
        "parse_cache",
        lambda _cache: {
            "begin_block": pool.begin_block,
            "end_block": pool.end_block,
            "begin_date": pool.begin_date,
            "end_date": pool.end_date,
            "lock_length_blocks": pool.lock_length_blocks,
        },
    )

    with pytest.raises(PoolStateIdentityConflictError, match="incompatible persisted"):
        await api_module.create_contract_with(
            type=contract.type,
            id=contract.id,
            version=contract.version,
            description=contract.description,
            metadata=contract.metadata,
        )

    assert legacy_contracts.count_documents({"id": contract.id}) == 1
    assert flex_database.staking_pools.mongodb_collection.count_documents({"id": contract.id}) == 1
    assert flex_database.pool_states.mongodb_collection.count_documents({"pool_id": contract.id}) == 1


@pytest.mark.parametrize("failure_after", ["contract", "pool"])
def test_registration_retry_recovers_partial_identity_graph(
    registration_databases,
    failure_after: str,
) -> None:
    legacy_database, flex_database = registration_databases
    legacy_contracts = legacy_database["contract"]
    ensure_contract_id_index(target_collection=legacy_contracts)
    ensure_database_indexes(flex_database)
    contract, pool, state = _registration_records()

    get_or_create_contract(
        contract,
        target_collection=legacy_contracts,
    )
    if failure_after == "pool":
        flex_database.staking_pools.get_or_create(pool)

    created = _persist_registration(
        legacy_contracts=legacy_contracts,
        flex_database=flex_database,
        contract=contract,
        pool=pool,
        state=state,
    )

    assert created is False
    assert legacy_contracts.count_documents({"id": contract.id}) == 1
    assert flex_database.staking_pools.mongodb_collection.count_documents({"id": contract.id}) == 1
    assert flex_database.pool_states.mongodb_collection.count_documents({"pool_id": contract.id}) == 1
