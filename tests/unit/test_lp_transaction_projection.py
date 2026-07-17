import asyncio
from types import SimpleNamespace

from flex import sync_pools
from flex.data import lp_states
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
        ),
    }
    created = []
    updated = []
    monkeypatch.setattr(
        lp_states,
        "db",
        SimpleNamespace(
            lp_transactions=SimpleNamespace(
                exists=lambda **kwargs: False,
                create_many=lambda values: created.extend(values),
            ),
            lp_states=SimpleNamespace(
                get_one=lambda **kwargs: states[kwargs["address"]],
                update=updated.append,
            ),
        ),
    )

    async def unchanged(state):
        return state

    monkeypatch.setattr(
        lp_states,
        "recalculate_lp_state_price_algo_with_micros",
        unchanged,
    )

    result = asyncio.run(
        lp_states.update_lp_states_with_transactions(projections),
    )

    assert states["POOL-A"].asset1_reserve_micros == 95
    assert states["POOL-B"].asset1_reserve_micros == 205
    assert {state.address for state in result} == {"POOL-A", "POOL-B"}
    assert [tx.id for tx in created] == ["TX@POOL-A", "TX@POOL-B"]
