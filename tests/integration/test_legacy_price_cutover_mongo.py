import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bson import Decimal128
from pymongo import MongoClient
from pymongo.database import Database

from flex.db.indexes import delete_unverified_legacy_lp_prices

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
    database = client[f"cometa_legacy_price_cutover_{uuid4().hex}"]
    try:
        yield database
    finally:
        client.drop_database(database.name)
        client.close()


def test_cutover_deletes_both_legacy_signatures_and_preserves_safe_prices(
    mongo_database: Database,
) -> None:
    collection = mongo_database["asset_prices"]
    collection.insert_many(
        [
            {"id": Decimal128("1"), "source": "vestige"},
            {
                "id": Decimal128("2"),
                "source": "tinyman",
                "tinyman_algo_pool_id": None,
            },
            {"id": Decimal128("3")},
            {
                "id": Decimal128("4"),
                "source": "vestige",
                "tinyman_algo_pool_id": Decimal128("99"),
            },
            {"id": Decimal128("5"), "source": "derived_lp"},
            {
                "id": Decimal128("6"),
                "source": "derived_lp",
                "tinyman_algo_pool_id": None,
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

    remaining_ids = {document["id"].to_decimal() for document in collection.find({}, projection={"id": 1})}
    assert removed == 3
    assert remaining_ids == {1, 2, 3}
