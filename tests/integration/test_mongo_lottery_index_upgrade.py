import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

pytestmark = pytest.mark.integration


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
    database_name = f"cometa_lottery_index_{uuid4().hex}"
    database = client[database_name]
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def test_old_lottery_id_index_is_replaced_without_a_uniqueness_gap(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    collection = mongo_database["lottery_draws"]
    collection.insert_many(
        [
            {"marker": "missing-id"},
            {"marker": "empty-id", "id": ""},
            {"marker": "current", "id": "draw-current"},
        ]
    )
    collection.create_index(
        "id",
        unique=True,
        name="id_unique",
        partialFilterExpression={"id": {"$type": "string"}},
    )
    original_ids = set(collection.distinct("_id"))
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    nft_lottery.ensure_lottery_indexes()

    assert set(collection.distinct("_id")) == original_ids
    indexes = collection.index_information()
    assert "id_unique" not in indexes
    replacement = indexes[nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME]
    assert replacement["unique"] is True
    assert replacement["partialFilterExpression"] == nft_lottery.LOTTERY_DRAW_ID_FILTER

    # The upgraded filter intentionally leaves legacy placeholders outside the
    # index while continuing to reject every duplicate durable draw identity.
    collection.insert_many([{"id": ""}, {"id": ""}, {"marker": "another-missing-id"}])
    with pytest.raises(DuplicateKeyError):
        collection.insert_one({"id": "draw-current"})


def test_lottery_id_index_upgrade_preserves_conflicting_records(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    collection = mongo_database["lottery_draws"]
    collection.insert_many(
        [
            {"marker": "first", "id": "duplicate"},
            {"marker": "second", "id": "duplicate"},
        ]
    )
    original_ids = set(collection.distinct("_id"))
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    with pytest.raises(RuntimeError, match="preserved 1 duplicate group"):
        nft_lottery.ensure_lottery_indexes()

    assert set(collection.distinct("_id")) == original_ids
    assert nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME not in collection.index_information()


def test_staking_entitlement_allows_only_one_concurrent_draw(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    draws = mongo_database["lottery_draws"]
    entitlements = mongo_database["lottery_entitlements"]
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=draws),
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_entitlements",
        entitlements,
    )
    monkeypatch.setattr(
        nft_lottery,
        "draw_id",
        lambda lottery: 777,
    )
    lottery = nft_lottery.NftLottery(
        name="staking-summer",
        asset_id=7,
        min_amount=1,
        probability=1.0,
        available_nfts=[777],
        type=nft_lottery.LotteryType.STAKING,
    )
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)

    def create_draw(_: int):
        return nft_lottery._get_or_create_staking_draw(
            lottery,
            "WALLET",
            now=now,
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(create_draw, range(32)))

    materialized = [draw for draw in results if draw is not None]
    assert materialized
    assert len({draw.id for draw in materialized}) == 1
    assert draws.count_documents({}) == 1
    entitlement = entitlements.find_one({})
    assert entitlement is not None
    assert entitlement["generation"] == 1
    assert entitlement["active"]["draw_id"] == materialized[0].id
    assert entitlement["active"]["status"] == nft_lottery.StakingEntitlementStatus.MATERIALIZED


def test_staking_entitlement_recovers_a_crash_before_draw_insert(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    draws = mongo_database["lottery_draws"]
    entitlements = mongo_database["lottery_entitlements"]
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=draws),
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_entitlements",
        entitlements,
    )
    monkeypatch.setattr(
        nft_lottery,
        "draw_id",
        lambda lottery: 888,
    )
    lottery = nft_lottery.NftLottery(
        name="staking-recovery",
        asset_id=7,
        min_amount=1,
        probability=1.0,
        available_nfts=[888],
        type=nft_lottery.LotteryType.STAKING,
    )
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    claimed = nft_lottery._claim_staking_entitlement(
        lottery_name=lottery.name,
        wallet="WALLET",
        now=now,
    )

    assert claimed is not None
    assert draws.count_documents({}) == 0

    recovered = nft_lottery._get_or_create_staking_draw(
        lottery,
        "WALLET",
        now=now,
    )

    assert recovered is not None
    assert recovered.id == claimed["active"]["draw_id"]
    assert recovered.prize == 888
    assert draws.count_documents({}) == 1


def test_staking_entitlement_repairs_confirmed_draw_before_next_generation(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    draws = mongo_database["lottery_draws"]
    entitlements = mongo_database["lottery_entitlements"]
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=draws),
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_entitlements",
        entitlements,
    )
    monkeypatch.setattr(
        nft_lottery,
        "draw_id",
        lambda lottery: 999,
    )
    lottery = nft_lottery.NftLottery(
        name="staking-confirmed-repair",
        asset_id=7,
        min_amount=1,
        probability=1.0,
        available_nfts=[999],
        type=nft_lottery.LotteryType.STAKING,
    )
    first_time = datetime(2026, 7, 19, 12, tzinfo=UTC)
    first = nft_lottery._get_or_create_staking_draw(
        lottery,
        "WALLET",
        now=first_time,
    )
    assert first is not None
    draws.update_one(
        {"id": first.id},
        {
            "$set": {
                "claimed": True,
                "payout_status": nft_lottery.LotteryPayoutStatus.CONFIRMED,
            }
        },
    )

    second = nft_lottery._get_or_create_staking_draw(
        lottery,
        "WALLET",
        now=first_time + timedelta(seconds=nft_lottery.MIN_DRAW_INTERVAL),
    )

    assert second is not None
    assert second.id != first.id
    entitlement = entitlements.find_one({})
    assert entitlement is not None
    assert entitlement["generation"] == 2


def test_confirmed_staking_entitlement_is_terminal_against_stale_error(
    mongo_database: Database,
    monkeypatch,
) -> None:
    from api import nft_lottery

    entitlements = mongo_database["lottery_entitlements"]
    monkeypatch.setattr(
        nft_lottery,
        "lottery_entitlements",
        entitlements,
    )
    entitlements.insert_one(
        {
            "_id": "entitlement",
            "generation": 1,
            "active": {
                "draw_id": "draw",
                "status": nft_lottery.StakingEntitlementStatus.CONFIRMED,
            },
        }
    )
    draw = nft_lottery.LotteryDraw(
        id="draw",
        wallet="WALLET",
        prize=999,
        entitlement_id="entitlement",
        entitlement_generation=1,
    )

    nft_lottery._update_staking_entitlement_status(
        draw,
        nft_lottery.StakingEntitlementStatus.UNRESOLVED,
    )

    persisted = entitlements.find_one({"_id": "entitlement"})
    assert persisted is not None
    assert persisted["active"]["status"] == nft_lottery.StakingEntitlementStatus.CONFIRMED
