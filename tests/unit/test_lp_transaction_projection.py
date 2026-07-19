import asyncio
from types import SimpleNamespace

import pytest

from flex import sync_pools
from flex.data import lp_states
from flex.db.lp_projection import (
    LpProjectionOutcome,
    LpProjectionResult,
)
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.domain.algorand import MAX_ALGORAND_UINT
from flex.domain.transactions import ASSET_TRANSFER_TX, PAYMENT_TX


def test_lp_to_lp_transfer_updates_both_scoped_projections(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {
            "POOL-A": frozenset({0, 7, 99}),
            "POOL-B": frozenset({0, 7, 98}),
        },
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL-A",
        "confirmed-round": 123,
        "fee": 0,
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
            raise AssertionError("ledger projection must not persist derived prices")

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

    recalculation_calls = 0

    async def forbidden_recalculation(state):
        nonlocal recalculation_calls
        recalculation_calls += 1
        raise AssertionError("ledger projection must not recalculate prices")

    # Keep this sentinel even though the production symbol has been removed:
    # the test fails if a future implementation reintroduces and calls it.
    monkeypatch.setattr(
        lp_states,
        "recalculate_lp_state_price_algo_with_micros",
        forbidden_recalculation,
        raising=False,
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
    assert recalculation_calls == 0


def test_lp_self_transfer_has_zero_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 0,
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


def test_lp_asset_transfer_projects_pool_fee_as_separate_algo_debit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "USER",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(tx.id, tx.asa_id, tx.delta_amount_micros) for tx in projections] == [
        ("TX@POOL", 7, -5),
        ("TX#fee@POOL", 0, -1_000),
    ]


def test_token_token_pool_fee_is_a_separately_projectable_algo_event(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 8, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "USER",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(tx.id, tx.asa_id, tx.delta_amount_micros) for tx in projections] == [
        ("TX@POOL", 7, -5),
        ("TX#fee@POOL", 0, -1_000),
    ]


def test_lp_payment_projects_amount_and_fee_as_distinct_algo_debits(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        PAYMENT_TX: {
            "amount": 5,
            "receiver": "USER",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(tx.id, tx.asa_id, tx.delta_amount_micros) for tx in projections] == [
        ("TX@POOL", 0, -5),
        ("TX#fee@POOL", 0, -1_000),
    ]


def test_lp_self_transfer_still_projects_pool_fee(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "POOL",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(tx.id, tx.pool_address, tx.asa_id, tx.delta_amount_micros) for tx in projections] == [
        ("TX#fee@POOL", "POOL", 0, -1_000),
    ]


def test_unrelated_asset_dust_cannot_block_lp_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 8, 99})},
    )
    raw_transaction = {
        "id": "DUST",
        "sender": "ATTACKER",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 666,
            "amount": 1,
            "receiver": "POOL",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert projections == []


def test_unrelated_clawback_cannot_block_pool_fee_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 8, 99})},
    )
    raw_transaction = {
        "id": "UNRELATED-CLAWBACK",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 666,
            "amount": 1,
            "sender": "VICTIM",
            "receiver": "ATTACKER",
        },
    }

    projections = asyncio.run(
        sync_pools.process_lp_transactions([raw_transaction]),
    )

    assert [(transaction.id, transaction.asa_id, transaction.delta_amount_micros) for transaction in projections] == [
        ("UNRELATED-CLAWBACK#fee@POOL", 0, -1_000),
    ]


@pytest.mark.parametrize(
    "invalid_fee",
    [None, -1, MAX_ALGORAND_UINT + 1, 1.5, True, "1000"],
)
def test_lp_projection_rejects_invalid_algorand_fees(
    monkeypatch,
    invalid_fee,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": invalid_fee,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "USER",
        },
    }

    with pytest.raises(ValueError, match="fee must be an Algorand uint64"):
        asyncio.run(
            sync_pools.process_lp_transactions([raw_transaction]),
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("amount", True),
        ("amount", -1),
        ("amount", MAX_ALGORAND_UINT + 1),
        ("amount", "5"),
        ("asset-id", True),
        ("asset-id", 0),
        ("asset-id", MAX_ALGORAND_UINT + 1),
    ],
)
def test_lp_projection_rejects_invalid_asset_transfer_uint64_fields(
    monkeypatch,
    field: str,
    invalid_value: object,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    transfer = {
        "asset-id": 7,
        "amount": 5,
        "receiver": "USER",
    }
    transfer[field] = invalid_value
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": 123,
        "fee": 1_000,
        ASSET_TRANSFER_TX: transfer,
    }

    with pytest.raises(ValueError, match=field):
        asyncio.run(sync_pools.process_lp_transactions([raw_transaction]))


@pytest.mark.parametrize(
    "invalid_round",
    [True, -1, MAX_ALGORAND_UINT + 1, 1.5, "123", None],
)
def test_lp_projection_rejects_invalid_confirmed_round_before_negation(
    monkeypatch,
    invalid_round: object,
) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
    )
    raw_transaction = {
        "id": "TX",
        "sender": "POOL",
        "confirmed-round": invalid_round,
        "fee": 1_000,
        ASSET_TRANSFER_TX: {
            "asset-id": 7,
            "amount": 5,
            "receiver": "USER",
        },
    }

    with pytest.raises(ValueError, match="confirmed-round"):
        asyncio.run(sync_pools.process_lp_transactions([raw_transaction]))


def test_lp_sync_module_has_no_raw_balance_price_publisher() -> None:
    assert not hasattr(sync_pools, "update_asset_prices")
    assert not hasattr(sync_pools, "create_and_update_asset_prices")


def test_token_token_snapshot_tracks_operational_algo_without_repricing(
    monkeypatch,
) -> None:
    state = LpState(
        id=1,
        address="POOL",
        token_id=99,
        asset1_id=7,
        asset2_id=8,
        dex_provider="tinyman",
        last_updated_round=122,
        asset1_reserve_micros=1,
        asset2_reserve_micros=2,
        total_tokens_micros=3,
        operational_algo_balance_micros=4,
        asset1_reserve=1.0,
        asset2_reserve=2.0,
        total_tokens=3.0,
        token_price_algo=12.5,
    )

    async def snapshot(address, *, include_algo):
        assert address == "POOL"
        assert include_algo is True
        return SimpleNamespace(
            balances={0: 5_000, 7: 100, 8: 200, 99: 20},
            observed_round=123,
        )

    async def total_supply(asset_id):
        assert asset_id == 99
        return 100

    class FakeRepository:
        def replace_snapshot(self, requested_state, *, observed_round):
            assert observed_round == 123
            return requested_state

    monkeypatch.setattr(lp_states, "get_address_asset_snapshot", snapshot)
    monkeypatch.setattr(lp_states, "get_asset_total_supply", total_supply)
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
        lambda **kwargs: FakeRepository(),
    )

    updated = asyncio.run(lp_states.update_lp_state(state))

    assert state.asset1_reserve_micros == 1
    assert state.asset2_reserve_micros == 2
    assert state.total_tokens_micros == 3
    assert state.operational_algo_balance_micros == 4
    assert updated.asset1_reserve_micros == 100
    assert updated.asset2_reserve_micros == 200
    assert updated.total_tokens_micros == 80
    assert updated.operational_algo_balance_micros == 5_000
    assert updated.token_price_algo == 12.5


def test_lp_projection_rejects_clawback_semantics(monkeypatch) -> None:
    monkeypatch.setattr(
        sync_pools,
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
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
        "get_lp_tracked_assets_by_address",
        lambda: {"POOL": frozenset({0, 7, 99})},
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
