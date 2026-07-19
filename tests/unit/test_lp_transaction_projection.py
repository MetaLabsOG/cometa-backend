import asyncio
from types import SimpleNamespace

import pytest

from flex import sync_pools
from flex.data import lp_states
from flex.db.lp_projection import (
    LpProjectionOutcome,
    LpProjectionResult,
)
from flex.db.model.liquidity_pools import LpTransaction
from flex.domain.transactions import ASSET_TRANSFER_TX


def test_lp_to_lp_transfer_updates_both_scoped_projections(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_all_lp_state_addresses",
        lambda: {"POOL-A", "POOL-B"},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL-A",
        "confirmed-round": 123,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "POOL-B",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(tx.id, tx.pool_address, tx.delta_amount_micros) for tx in projections] == [
        ("TX@POOL-A", "POOL-A", -5),
        ("TX@POOL-B", "POOL-B", 5),
    ]

    states = {
        "POOL-A": SimpleNamespace(
            id=1,
            address="POOL-A",
            token_id=99,
            asset1_id=7,
            asset2_id=0,
            asset1_reserve_micros=100,
            asset2_reserve_micros=100,
            total_tokens_micros=100,
            last_updated_round=0,
            last_event_order=None,
        ),
        "POOL-B": SimpleNamespace(
            id=2,
            address="POOL-B",
            token_id=98,
            asset1_id=7,
            asset2_id=0,
            asset1_reserve_micros=200,
            asset2_reserve_micros=200,
            total_tokens_micros=200,
            last_updated_round=0,
            last_event_order=None,
        ),
    }

    class FakeProjectionRepository:
        def __init__(self) -> None:
            self.projected = []

        def project(self, transaction):
            self.projected.append(transaction)
            state = states[transaction.pool_address]
            state.asset1_reserve_micros += transaction.delta_amount_micros
            state.last_event_order = transaction.event_order
            return LpProjectionOutcome(
                state=state,
                result=LpProjectionResult.APPLIED,
            )

        def get_state(self, pool_address):
            return states[pool_address]

        def update_derived_fields(self, state, *, expected_cursor):
            assert state.last_event_order == expected_cursor
            return state

    repository = FakeProjectionRepository()
    monkeypatch.setattr(
        lp_states,
        "db",
        SimpleNamespace(
            lp_transactions=SimpleNamespace(mongodb_collection=object()),
            lp_states=SimpleNamespace(mongodb_collection=object()),
        ),
    )
    monkeypatch.setattr(
        lp_states,
        "MongoLpProjectionRepository",
        lambda **kwargs: repository,
    )

    async def unchanged(state):
        return state

    monkeypatch.setattr(
        lp_states,
        "recalculate_lp_state_price_algo_with_micros",
        unchanged,
    )

    result = asyncio.run(
        lp_states.update_lp_states_with_transactions(
            projections,
            expected_round=123,
        ),
    )

    assert states["POOL-A"].asset1_reserve_micros == 95
    assert states["POOL-B"].asset1_reserve_micros == 205
    assert {state.address for state in result} == {"POOL-A", "POOL-B"}
    assert [tx.id for tx in repository.projected] == ["TX@POOL-A", "TX@POOL-B"]


def test_lp_self_transfer_has_zero_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_all_lp_state_addresses",
        lambda: {"POOL"},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "POOL",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert projections == []


def test_lp_projection_rejects_clawback_semantics(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_all_lp_state_addresses",
        lambda: {"POOL"},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "CLAWBACK",
        "confirmed-round": 123,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "POOL",
            "sender": "VICTIM",
        },
    }

    with pytest.raises(ValueError, match="clawback/close"):
        asyncio.run(
            sync_pools.process_lp_transactions([raw_transaction]),
        )


def test_lp_projection_ignores_unrelated_clawback(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_all_lp_state_addresses",
        lambda: {"POOL"},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "CLAWBACK",
        "confirmed-round": 123,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "OTHER",
            "sender": "VICTIM",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert projections == []


def test_lp_batch_preflight_rejects_conflicts_before_projection() -> None:
    original = LpTransaction(
        id="TX@POOL",
        pool_address="POOL",
        user_address="USER",
        asa_id=7,
        delta_amount_micros=5,
        confirmed_round=123,
        event_position=1,
    )
    conflicting = LpTransaction(
        id="TX@POOL",
        pool_address="POOL",
        user_address="USER",
        asa_id=7,
        delta_amount_micros=6,
        confirmed_round=123,
        event_position=1,
    )

    with pytest.raises(
        lp_states.LpProjectionPersistenceError,
        match="conflicting data",
    ):
        lp_states._preflight_lp_transactions(
            [original, conflicting],
            expected_round=123,
        )


def test_lp_batch_preflight_deduplicates_exact_replay() -> None:
    transaction = LpTransaction(
        id="TX@POOL",
        pool_address="POOL",
        user_address="USER",
        asa_id=7,
        delta_amount_micros=5,
        confirmed_round=123,
        event_position=1,
    )

    canonical = lp_states._preflight_lp_transactions(
        [transaction, transaction],
        expected_round=123,
    )

    assert canonical == [transaction]


def test_snapshot_checkpoint_uses_slowest_indexer_observation() -> None:
    states = [
        SimpleNamespace(
            last_updated_round=105,
            last_event_order="00000000000000000105:~",
        ),
        SimpleNamespace(
            last_updated_round=102,
            last_event_order="00000000000000000102:~",
        ),
    ]

    checkpoint = sync_pools._snapshot_checkpoint_round(
        previous_round=100,
        node_round=110,
        lp_states=states,
    )

    assert checkpoint == 102


def test_snapshot_checkpoint_without_lp_states_uses_node_round() -> None:
    checkpoint = sync_pools._snapshot_checkpoint_round(
        previous_round=100,
        node_round=110,
        lp_states=[],
    )

    assert checkpoint == 110


def test_snapshot_checkpoint_rejects_indexer_regression() -> None:
    states = [
        SimpleNamespace(
            last_updated_round=99,
            last_event_order="00000000000000000099:~",
        )
    ]

    with pytest.raises(
        sync_pools.SyncCoordinatorError,
        match="Indexer snapshots lag",
    ):
        sync_pools._snapshot_checkpoint_round(
            previous_round=100,
            node_round=110,
            lp_states=states,
        )


def test_snapshot_checkpoint_does_not_skip_rest_of_partial_round() -> None:
    states = [
        SimpleNamespace(
            last_updated_round=101,
            last_event_order=("00000000000000000101:00000000000000000002:TX@POOL"),
        )
    ]

    checkpoint = sync_pools._snapshot_checkpoint_round(
        previous_round=100,
        node_round=110,
        lp_states=states,
    )

    assert checkpoint == 100
