from datetime import UTC, datetime

import pytest
from bson import BSON, Decimal128

from flex.db.model.blockchain import TOTAL_SUPPLY_SOURCE_INDEXER, Asset, LpToken
from flex.db.model.liquidity_pools import LpState
from flex.db.model.priced import AssetPrice
from flex.db.model.transfers import AssetTransferIntent

UINT64_MAX = 2**64 - 1


def test_lp_token_round_trips_full_uint64_identifiers() -> None:
    token = LpToken(
        id=UINT64_MAX,
        asset1_id=UINT64_MAX - 1,
        asset2_id=0,
        dex_provider="tinyman",
        address="POOL",
        pool_id=UINT64_MAX,
    )

    restored = LpToken.from_dict(
        BSON(BSON.encode(token.to_dict())).decode(),
    )

    assert restored.id == UINT64_MAX
    assert restored.asset1_id == UINT64_MAX - 1
    assert restored.pool_id == UINT64_MAX
    assert LpToken.encode_query({"id": UINT64_MAX}) == {
        "id": Decimal128(str(UINT64_MAX)),
    }


def test_asset_round_trips_full_uint64_identifier_and_supply() -> None:
    asset = Asset(
        id=UINT64_MAX,
        name="MAX",
        decimals=0,
        unit_name="MAX",
        creator="CREATOR",
        reserve="RESERVE",
        total_supply=0,
        total_supply_micros=UINT64_MAX,
        total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
    )

    restored = Asset.from_dict(
        BSON(BSON.encode(asset.to_dict())).decode(),
    )

    assert restored.id == UINT64_MAX
    assert restored.total_supply_micros == UINT64_MAX
    assert Asset.encode_query({"id": UINT64_MAX}) == {
        "id": Decimal128(str(UINT64_MAX)),
    }


def test_asset_price_round_trips_full_uint64_identifiers_and_round() -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    price = AssetPrice(
        id=UINT64_MAX,
        price_usd=1,
        price_algo=2,
        last_update_round=UINT64_MAX,
        name="MAX",
        tinyman_algo_pool_id=UINT64_MAX,
        source="tinyman",
        observed_at=observed_at,
    )

    restored = AssetPrice.from_dict(
        BSON(BSON.encode(price.to_dict())).decode(),
    )

    assert restored.id == UINT64_MAX
    assert restored.last_update_round == UINT64_MAX
    assert restored.tinyman_algo_pool_id == UINT64_MAX
    assert AssetPrice.encode_query({"id": UINT64_MAX}) == {
        "id": Decimal128(str(UINT64_MAX)),
    }


def test_transfer_intent_round_trips_full_uint64_rounds() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    intent = AssetTransferIntent(
        id="airdrop:max-round",
        receiver="receiver",
        asset_id="1",
        amount_micros="1",
        note=None,
        signed_transaction="signed",
        txid="txid",
        first_valid_round=UINT64_MAX - 1,
        last_valid_round=UINT64_MAX,
        status="confirmed",
        confirmed_round=UINT64_MAX,
        created=timestamp,
        updated=timestamp,
    )

    encoded = intent.to_dict()
    restored = AssetTransferIntent.from_dict(
        BSON(BSON.encode(encoded)).decode(),
    )

    assert encoded["first_valid_round"] == Decimal128(str(UINT64_MAX - 1))
    assert encoded["last_valid_round"] == Decimal128(str(UINT64_MAX))
    assert encoded["confirmed_round"] == Decimal128(str(UINT64_MAX))
    assert restored.first_valid_round == UINT64_MAX - 1
    assert restored.last_valid_round == UINT64_MAX
    assert restored.confirmed_round == UINT64_MAX


def test_lp_state_rejects_invalid_balance_before_initial_insert() -> None:
    with pytest.raises(ValueError, match="asset1_reserve_micros"):
        LpState(
            id=1,
            token_id=99,
            asset1_id=7,
            asset2_id=0,
            dex_provider="tinyman",
            address="POOL",
            last_updated_round=1,
            asset1_reserve_micros=True,
            asset2_reserve_micros=1,
            total_tokens_micros=1,
            asset1_reserve=0,
            asset2_reserve=0,
            total_tokens=0,
            token_price_algo=0,
        )
