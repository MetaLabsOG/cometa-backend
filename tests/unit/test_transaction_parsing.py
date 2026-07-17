import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from flex.data import transactions as transaction_data
from flex.domain.transactions import (
    APPLICATION_CALL_TX,
    ASSET_TRANSFER_TX,
    INNER_TRANSACTIONS,
    PAYMENT_TX,
    TransactionShapeError,
    event_id_aliases,
    flatten_asset_transfers,
    flatten_transfer_payments,
    projection_event_id,
)


def test_recursive_flattening_builds_stable_path_ids_without_mutation() -> None:
    transactions = [
        {
            "id": "ROOT",
            APPLICATION_CALL_TX: {},
            INNER_TRANSACTIONS: [
                {ASSET_TRANSFER_TX: {"amount": 10}},
                {
                    APPLICATION_CALL_TX: {},
                    INNER_TRANSACTIONS: [
                        {PAYMENT_TX: {"amount": 20}},
                        {
                            APPLICATION_CALL_TX: {},
                            INNER_TRANSACTIONS: [
                                {ASSET_TRANSFER_TX: {"amount": 30}},
                            ],
                        },
                    ],
                },
            ],
        },
    ]
    original = deepcopy(transactions)

    first_result = flatten_transfer_payments(transactions)
    second_result = flatten_transfer_payments(transactions)

    assert [transaction["id"] for transaction in first_result] == [
        "ROOT#0",
        "ROOT#1#0",
        "ROOT#1#1#0",
    ]
    assert second_result == first_result
    assert transactions == original

    first_result[0][ASSET_TRANSFER_TX]["amount"] = 999
    assert transactions == original


def test_asset_transfer_filter_skips_entire_nested_payment_group() -> None:
    direct_transfer = {"id": "DIRECT", ASSET_TRANSFER_TX: {"amount": 1}}
    claim_group = {
        "id": "CLAIM",
        APPLICATION_CALL_TX: {},
        INNER_TRANSACTIONS: [
            {ASSET_TRANSFER_TX: {"amount": 2}},
            {
                APPLICATION_CALL_TX: {},
                INNER_TRANSACTIONS: [{PAYMENT_TX: {"amount": 3}}],
            },
        ],
    }
    stake_group = {
        "id": "STAKE",
        APPLICATION_CALL_TX: {},
        INNER_TRANSACTIONS: [{ASSET_TRANSFER_TX: {"amount": 4}}],
    }
    transactions = [direct_transfer, claim_group, stake_group]

    filtered = flatten_asset_transfers(transactions)
    unfiltered = flatten_asset_transfers(transactions, skip_groups_with_payments=False)

    assert [transaction["id"] for transaction in filtered] == ["DIRECT", "STAKE#0"]
    assert [transaction["id"] for transaction in unfiltered] == ["DIRECT", "CLAIM#0", "STAKE#0"]


def test_flattening_keeps_sibling_event_ids_unique() -> None:
    transactions = [
        {
            "id": "GROUP",
            APPLICATION_CALL_TX: {},
            INNER_TRANSACTIONS: [
                {ASSET_TRANSFER_TX: {"amount": 1}},
                {ASSET_TRANSFER_TX: {"amount": 2}},
            ],
        },
    ]

    result = flatten_asset_transfers(transactions)

    assert [transaction["id"] for transaction in result] == ["GROUP#0", "GROUP#1"]
    assert len({transaction["id"] for transaction in result}) == len(result)


def test_inner_event_aliases_include_legacy_root_id() -> None:
    assert event_id_aliases("ROOT#1#0") == ("ROOT#1#0", "ROOT")
    assert event_id_aliases("ROOT") == ("ROOT",)
    assert event_id_aliases("ROOT#1@POOL") == (
        "ROOT#1@POOL",
        "ROOT#1",
        "ROOT",
    )
    assert projection_event_id("ROOT#1", "POOL") == "ROOT#1@POOL"


def test_inner_event_inherits_root_confirmation_round() -> None:
    transactions = [
        {
            "id": "ROOT",
            "confirmed-round": 123,
            APPLICATION_CALL_TX: {},
            INNER_TRANSACTIONS: [
                {ASSET_TRANSFER_TX: {"amount": 10}},
            ],
        },
    ]

    assert flatten_asset_transfers(transactions)[0]["confirmed-round"] == 123


def test_linear_and_block_ingestion_use_the_same_inner_event_ids(monkeypatch) -> None:
    root_transaction = {
        "id": "ROOT",
        "confirmed-round": 123,
        "sender": "POOL",
        APPLICATION_CALL_TX: {},
        INNER_TRANSACTIONS: [
            {
                "sender": "POOL",
                ASSET_TRANSFER_TX: {
                    "asset-id": 7,
                    "amount": 10,
                    "receiver": "USER-A",
                },
            },
            {
                "sender": "POOL",
                ASSET_TRANSFER_TX: {
                    "asset-id": 7,
                    "amount": 20,
                    "receiver": "USER-B",
                },
            },
        ],
    }
    monkeypatch.setattr(
        transaction_data,
        "indexer_client",
        SimpleNamespace(
            search_transactions_by_address=lambda **kwargs: {
                "transactions": [root_transaction],
            },
        ),
    )

    linear = asyncio.run(
        transaction_data.pool_fetch_new_transactions_by_id(
            pool_id=99,
            asset_id=7,
            pool_address="POOL",
        ),
    )
    block = flatten_asset_transfers([root_transaction])

    assert {transaction.id for transaction in linear} == {transaction["id"] for transaction in block}


def test_linear_cursor_matches_canonical_inner_event_root(monkeypatch) -> None:
    transactions = [
        {
            "id": "NEW",
            "sender": "USER",
            "confirmed-round": 124,
            ASSET_TRANSFER_TX: {
                "asset-id": 7,
                "amount": 5,
                "receiver": "POOL",
            },
        },
        {
            "id": "ROOT",
            "confirmed-round": 123,
            APPLICATION_CALL_TX: {},
            INNER_TRANSACTIONS: [
                {
                    ASSET_TRANSFER_TX: {
                        "asset-id": 7,
                        "amount": 10,
                        "receiver": "USER-A",
                    },
                },
            ],
        },
        {
            "id": "OLDER",
            "sender": "USER",
            "confirmed-round": 122,
            ASSET_TRANSFER_TX: {
                "asset-id": 7,
                "amount": 99,
                "receiver": "POOL",
            },
        },
    ]
    monkeypatch.setattr(
        transaction_data,
        "indexer_client",
        SimpleNamespace(
            search_transactions_by_address=lambda **kwargs: {
                "transactions": transactions,
            },
        ),
    )

    result = asyncio.run(
        transaction_data.pool_fetch_new_transactions_by_id(
            pool_id=99,
            asset_id=7,
            last_tx_id="ROOT#0",
            pool_address="POOL",
        ),
    )

    assert [transaction.id for transaction in result] == ["NEW"]


@pytest.mark.parametrize(
    "transaction",
    [
        {APPLICATION_CALL_TX: {}},
        {"id": "ROOT", APPLICATION_CALL_TX: {}, INNER_TRANSACTIONS: "not-a-list"},
        {"id": "ROOT", APPLICATION_CALL_TX: {}, INNER_TRANSACTIONS: [None]},
    ],
)
def test_flattening_rejects_payloads_without_stable_shapes(transaction: dict) -> None:
    with pytest.raises(TransactionShapeError):
        flatten_transfer_payments([transaction])
