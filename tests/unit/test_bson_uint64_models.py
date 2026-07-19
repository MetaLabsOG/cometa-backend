from datetime import UTC, datetime

from bson import BSON, Decimal128

from flex.db.model.blockchain import Asset, LpToken
from flex.db.model.priced import AssetPrice

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
