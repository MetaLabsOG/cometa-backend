import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from aiocache import cached
from pymongo import ReturnDocument

from flex import db
from flex.blockchain.info import ALGO_ASSET, fetch_asset
from flex.db.bson import decode_bson_uint64
from flex.db.model.blockchain import (
    TOTAL_SUPPLY_SOURCE_INDEXER,
    Asset,
    AssetDetails,
    AssetInfo,
)
from flex.providers.tinyman import get_asset_logo_url
from flex.util import build_key_str

logger = logging.getLogger(__name__)


async def create_asset(asset_id: int) -> Asset:
    asset = await fetch_asset(asset_id)
    asset.logo_url = get_asset_logo_url(asset_id)
    db.assets.create(asset)
    logger.info(f"New Asset: id={asset.id}, name={asset.name}")
    return asset


@cached(ttl=300, namespace="full_asset", key_builder=build_key_str)
async def get_full_asset(asset_id: int) -> Asset:
    document = await asyncio.to_thread(
        db.assets.mongodb_collection.find_one,
        Asset.encode_query({"id": asset_id}),
        projection={"total_supply_micros": 1, "total_supply_source": 1},
    )
    if document is not None and _canonical_supply(document) is None:
        await _backfill_canonical_supply(asset_id, document)

    asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
    if asset is None:
        asset = await create_asset(asset_id)
    if not asset.total_supply_is_authoritative:
        raise RuntimeError(f"asset {asset_id} canonical supply migration could not be verified")
    return asset


def _canonical_supply(document: dict[str, Any] | None) -> int | None:
    if document is None or document.get("total_supply_source") != TOTAL_SUPPLY_SOURCE_INDEXER:
        return None
    value = document.get("total_supply_micros")
    return None if value is None else decode_bson_uint64(value)


async def _backfill_canonical_supply(
    asset_id: int,
    document: dict[str, Any],
) -> int:
    """Replace a lossy legacy display supply with authoritative Indexer units."""

    document_id = document.get("_id")
    if document_id is None:
        raise RuntimeError(f"asset {asset_id} is missing its MongoDB identity")

    authoritative = await fetch_asset(asset_id)
    total_supply_micros = authoritative.total_supply_micros
    updated = await asyncio.to_thread(
        db.assets.mongodb_collection.find_one_and_update,
        {
            "_id": document_id,
            "$or": [
                {"total_supply_micros": {"$exists": False}},
                {"total_supply_micros": None},
                {"total_supply_source": {"$ne": TOTAL_SUPPLY_SOURCE_INDEXER}},
            ],
        },
        {
            "$set": {
                "total_supply_micros": str(total_supply_micros),
                "total_supply_source": TOTAL_SUPPLY_SOURCE_INDEXER,
                "total_supply": authoritative.total_supply,
                "updated": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        updated = await asyncio.to_thread(
            db.assets.mongodb_collection.find_one,
            {"_id": document_id},
            projection={"total_supply_micros": 1, "total_supply_source": 1},
        )
    persisted_supply = _canonical_supply(updated)
    if persisted_supply is None:
        raise RuntimeError(f"asset {asset_id} canonical supply migration was not persisted")
    if persisted_supply != total_supply_micros:
        raise RuntimeError(f"asset {asset_id} canonical supply changed during migration")
    return persisted_supply


@cached(namespace="asset_total_supply", key_builder=build_key_str)
async def get_asset_total_supply(asset_id: int) -> int:
    query = Asset.encode_query({"id": asset_id})
    document = await asyncio.to_thread(
        db.assets.mongodb_collection.find_one,
        query,
        projection={"total_supply_micros": 1, "total_supply_source": 1},
    )
    canonical_supply = _canonical_supply(document)
    if canonical_supply is not None:
        return canonical_supply
    if document is not None:
        return await _backfill_canonical_supply(asset_id, document)
    return (await get_full_asset(asset_id)).total_supply_micros


@cached(namespace="asset_info", key_builder=build_key_str)
async def get_asset_info(asset_id: int) -> AssetInfo:
    return (await get_full_asset(asset_id)).to_info()


@cached(namespace="asset_details", key_builder=build_key_str)
async def get_asset_details(asset_id: int) -> AssetDetails:
    return (await get_full_asset(asset_id)).to_details()


async def get_asset_details_by_query(query_dict: dict) -> list[AssetDetails]:
    return [asset.to_details() for asset in db.assets.get_many_by_query(query_dict)]


@cached(ttl=20, namespace="all_asset_details", key="420")
async def get_all_asset_details() -> list[AssetDetails]:
    all_assets = db.assets.get_all()
    return [asset.to_details() for asset in all_assets]


async def micros_to_amount(asset_id: int, amount_micros: int) -> float:
    return (await get_full_asset(asset_id)).micros_to_amount(amount_micros)


async def amount_to_micros(asset_id: int, amount: float) -> int:
    return (await get_full_asset(asset_id)).amount_to_micros(amount)


async def load_all_assets_data() -> list[Asset]:
    logger.info("Loading all assets data.")

    asset_ids = {ALGO_ASSET.id}

    for pool in db.farming_pools.get_all():
        asset_ids.add(pool.stake_token.id)
        asset_ids.add(pool.reward_token.id)
        asset_ids.add(pool.first_token.id)
        asset_ids.add(pool.second_token.id)

    for pool in db.staking_pools.get_all():
        asset_ids.add(pool.stake_token.id)
        asset_ids.add(pool.reward_token.id)

    assets = []
    for asset_id in asset_ids:
        asset = await get_full_asset(asset_id)
        assets.append(asset)

    logger.info(f"{len(asset_ids)} assets data loaded.")
    return assets
