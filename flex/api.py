import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from aiocache import cached
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from core.db.contracts import get_active_contracts, get_contracts_by_type
from env import settings
from flex import db
from flex.data.asset_prices import (
    create_asset_prices_batch,
    get_all_asset_prices,
    get_asset_prices_by_query,
    validated_stored_asset_price,
)
from flex.data.assets import get_all_asset_details, get_asset_details_by_query, get_full_asset
from flex.db.model.blockchain import AssetDetails
from flex.db.model.priced import AssetPriceInfo

router = APIRouter()
logger = logging.getLogger(__name__)
PositiveAssetId = Annotated[int, Field(strict=True, gt=0)]
AssetId = Annotated[int, Field(strict=True, ge=0)]
QueryAssetId = Annotated[int, Query(ge=0)]


# LP API


class LpStatePricedRequest(BaseModel):
    """Select either one LP token or a bounded batch, never both."""

    lp_token_id: PositiveAssetId | None = None
    lp_token_ids: list[PositiveAssetId] | None = Field(
        default=None,
        min_length=1,
        max_length=250,
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "LpStatePricedRequest":
        if (self.lp_token_id is None) == (self.lp_token_ids is None):
            raise ValueError("provide exactly one of lp_token_id or lp_token_ids")
        if self.lp_token_ids is not None:
            self.lp_token_ids = list(dict.fromkeys(self.lp_token_ids))
        return self


@router.post("/lp/state/priced", tags=["LP"])
async def handle_get_lp_state_priced(body: LpStatePricedRequest):
    """Return LP token prices from asset_prices collection."""
    if body.lp_token_ids is not None:
        token_ids = body.lp_token_ids
    else:
        assert body.lp_token_id is not None  # Guaranteed by model validation.
        token_ids = [body.lp_token_id]

    prices = db.asset_prices.get_many_by_query({"id": {"$in": token_ids}})
    max_stale = timedelta(seconds=settings.asset_prices_max_stale)
    prices_by_id = {
        price.id: price
        for price in prices
        if validated_stored_asset_price(
            price,
            max_age=max_stale,
        )
        is not None
    }
    results = {
        str(token_id): (
            {
                "token_id": token_id,
                "token_price_algo": prices_by_id[token_id].price_algo,
                "token_price_usd": prices_by_id[token_id].price_usd,
            }
            if token_id in prices_by_id
            else None
        )
        for token_id in token_ids
    }

    if body.lp_token_ids is not None:
        return {"results": results}
    # Single mode: backward compatible
    return results.get(str(body.lp_token_id))


# ASSETS API


@router.post("/asset", tags=["Assets"])
async def handle_get_asset_by_id(asset_id: QueryAssetId) -> AssetDetails:
    asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset.to_details()


@router.post("/asset/price", tags=["Assets"])
async def handle_get_asset_price_by_id(asset_id: QueryAssetId) -> AssetPriceInfo:
    current_time = datetime.now(UTC)
    asset_price = db.asset_prices.get_one(id=asset_id)
    if asset_price is None:
        raise HTTPException(status_code=404, detail=f"Price for asset {asset_id} not found")
    if (
        validated_stored_asset_price(
            asset_price,
            max_age=timedelta(seconds=settings.asset_prices_max_stale),
            now=current_time,
        )
        is None
    ):
        raise HTTPException(
            status_code=503,
            detail=f"Price for asset {asset_id} is temporarily unavailable",
        )
    return asset_price.to_info(current_time)


class AssetsParams(BaseModel):
    ids: list[AssetId] | None = Field(
        default=None,
        min_length=1,
        max_length=250,
    )

    @model_validator(mode="after")
    def deduplicate_ids(self) -> "AssetsParams":
        if self.ids is not None:
            self.ids = list(dict.fromkeys(self.ids))
        return self

    def to_query_dict(self) -> dict:
        query_dict = {}
        if self.ids:
            query_dict["id"] = {"$in": self.ids}
        return query_dict


@router.post("/assets", tags=["Assets"])
async def handle_get_assets_by(params: AssetsParams) -> list[AssetDetails]:
    query_dict = params.to_query_dict()
    if len(query_dict) == 0:
        return await get_all_asset_details()
    return await get_asset_details_by_query(query_dict)


@router.post("/assets/price", tags=["Assets"])
async def handle_get_assets_prices_by(params: AssetsParams) -> list[AssetPriceInfo]:
    query_dict = params.to_query_dict()
    current_time = datetime.now(UTC)
    if len(query_dict) == 0:
        return await get_all_asset_prices(current_time=current_time)
    else:
        return await get_asset_prices_by_query(query_dict, current_time=current_time)


# ENRICHED FARM ENDPOINT


def _parse_bignum_safe(obj) -> int | None:
    if obj is None:
        return None
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict) and obj.get("type") == "BigNumber" and "hex" in obj:
        return int(obj["hex"], 16)
    return None


def serialize_contract_slim(contract) -> dict:
    meta = dict(contract.metadata) if contract.metadata else {}
    cache = meta.pop("cache", None)
    if cache:
        initial = cache.get("initial", {})
        global_state = cache.get("global", {})
        meta["begin_block"] = meta.get("begin_block") or _parse_bignum_safe(initial.get("beginBlock"))
        meta["end_block"] = meta.get("end_block") or _parse_bignum_safe(initial.get("endBlock"))
        meta["lock_length_blocks"] = meta.get("lock_length_blocks") or _parse_bignum_safe(
            initial.get("lockLengthBlocks")
        )
        meta["total_staked"] = _parse_bignum_safe(global_state.get("totalStaked"))
        meta["reward_per_token"] = _parse_bignum_safe(global_state.get("rewardPerTokenStored"))
        meta["total_reward_amount"] = _parse_bignum_safe(initial.get("totalRewardAmount"))
        meta["total_algo_reward_amount"] = _parse_bignum_safe(initial.get("totalAlgoRewardAmount"))
        meta["stake_token"] = _parse_bignum_safe(initial.get("stakeToken")) or _parse_bignum_safe(initial.get("token"))
        meta["reward_token"] = _parse_bignum_safe(initial.get("rewardToken")) or _parse_bignum_safe(
            initial.get("token")
        )
        meta["last_update_block"] = _parse_bignum_safe(global_state.get("lastUpdateBlock"))
    return {
        "type": contract.type,
        "id": contract.id,
        "version": contract.version,
        "deployed_timestamp": contract.deployed_timestamp,
        "description": contract.description,
        "metadata": meta,
        "begin_date": contract.begin_date.isoformat() if contract.begin_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
    }


@router.get("/contracts/farm/enriched", tags=["Contracts"])
@cached(
    ttl=60,
    namespace="farm_enriched",
    key_builder=lambda f, *args, **kwargs: (
        f"farm_enriched:active={kwargs.get('active_only', args[0] if args else True)}"
    ),
)
async def get_farm_enriched(active_only: bool = True):
    if active_only:
        farm_contracts = get_active_contracts("farm")
        distribution_contracts = get_active_contracts("distribution")
    else:
        farm_contracts = get_contracts_by_type("farm")
        distribution_contracts = get_contracts_by_type("distribution")
    contracts = farm_contracts + distribution_contracts

    # Collect asset IDs and LP token IDs from ALL pool contracts (farm + distribution)
    # so that user's ended pools also have pre-populated data
    all_contracts = get_contracts_by_type(None)

    asset_ids = set()
    for c in all_contracts:
        m = c.metadata or {}
        for key in ("stake_token_id", "reward_token_id", "asset1_id", "asset2_id"):
            val = m.get(key)
            if val is not None:
                asset_ids.add(int(val))

        cache = m.get("cache")
        if cache:
            initial = cache.get("initial", {})
            for key in ("stakeToken", "rewardToken", "token"):
                val = _parse_bignum_safe(initial.get(key))
                if val is not None:
                    asset_ids.add(val)

    asset_ids.discard(0)  # ALGO doesn't need lookup

    # Batch-fetch assets from DB, auto-populate missing ones from algod
    current_time = datetime.now(UTC)
    assets_list = db.assets.get_many_by_query({"id": {"$in": list(asset_ids)}}) if asset_ids else []
    existing_asset_ids = {a.id for a in assets_list}
    missing_asset_ids = asset_ids - existing_asset_ids
    if missing_asset_ids:
        logger.info(f"Auto-populating {len(missing_asset_ids)} missing assets from algod")

        async def _fetch_asset_safe(aid):
            try:
                return await get_full_asset(aid)
            except Exception as e:
                logger.warning(f"Failed to fetch asset {aid}: {e}")
                return None

        fetched = await asyncio.gather(*[_fetch_asset_safe(aid) for aid in missing_asset_ids])
        assets_list.extend(a for a in fetched if a is not None)

    # Batch-fetch prices from DB, auto-populate missing ones via batch Vestige API
    all_price_ids = asset_ids | {0}
    prices_list = db.asset_prices.get_many_by_query({"id": {"$in": list(all_price_ids)}})
    prices_list = [
        price
        for price in prices_list
        if validated_stored_asset_price(
            price,
            max_age=timedelta(seconds=settings.asset_prices_max_stale),
            now=current_time,
        )
        is not None
    ]
    existing_price_ids = {p.id for p in prices_list}
    missing_price_ids = all_price_ids - existing_price_ids
    if missing_price_ids:
        logger.info(f"Auto-populating {len(missing_price_ids)} missing prices (batch)")
        from flex.blockchain.info import get_current_round

        try:
            current_round = await get_current_round()
            new_prices = await create_asset_prices_batch(list(missing_price_ids), current_round)
            prices_list.extend(new_prices)
            logger.info(f"Batch created {len(new_prices)}/{len(missing_price_ids)} prices")
        except Exception as e:
            logger.error(f"Batch price creation failed: {e}")

    # This route only consumes independently validated stored observations.
    # No active publisher derives LP prices from pool-account balances.
    # Keep lp_states empty for frontend compatibility.
    lp_states_dict = {}

    assets_dict = {a.id: a.to_details().to_dict() for a in assets_list}
    prices_dict = {p.id: p.to_info(current_time).to_dict() for p in prices_list}

    return {
        "contracts": [serialize_contract_slim(c) for c in contracts],
        "assets": assets_dict,
        "prices": prices_dict,
        "lp_states": lp_states_dict,
    }
