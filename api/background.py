import asyncio
import logging
import multiprocessing
import random
from contextlib import contextmanager
from datetime import UTC, datetime

from api.stats import save_snapshot
from blockchain.node import get_current_round
from core.circuit_breaker import CircuitOpenError, get_circuit_breaker
from core.cometa import calculate_tvl_for_type
from core.db.contracts import get_contracts_by_type, update_contract
from core.db.model import PoolType
from core.decorators import repeat_every, safe_async_method
from core.js_interop import calljs
from core.util import parse_bignum, strip_version, with_exponential_backoff
from env import settings
from flex import db
from flex.application.price_refresh import (
    PriceProviderUnavailableError,
    PriceRefreshError,
)
from flex.blockchain.contract_state import fetch_contracts_views_batch
from flex.data.asset_prices import (
    create_asset_price,
    is_asset_price_stale,
    update_asset_price,
)
from flex.data.lp_prices import get_lp_token_definitions, update_lp_token_prices
from flex.migrations import migrate_background
from flex.sync_pools import sync_pools_loop

spawn = multiprocessing.get_context("spawn")
logger = logging.getLogger(__name__)


async def safe_background_task(coro, task_name="Unnamed"):
    """Wrapper to prevent background tasks from crashing the process"""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Background task '{task_name}' error: {e}", exc_info=True)
        await asyncio.sleep(5)


@safe_async_method
async def update_contracts_cache(type: str) -> None:
    start_time = datetime.now(UTC)

    all_contracts = get_contracts_by_type(type)
    contracts = []
    skipped = 0

    try:
        for contract in all_contracts:
            if contract.metadata is None or contract.metadata.get("cache") is None:
                contracts.append(contract)
            else:
                end_block = parse_bignum(contract.metadata["cache"]["initial"]["endBlock"])
                staked_microtokens = parse_bignum(contract.metadata["cache"]["global"]["totalStaked"])
                if end_block < get_current_round() and staked_microtokens <= 1:
                    skipped += 1
                    continue
                contracts.append(contract)
    except Exception as e:
        logger.error(f"Failed to filter contracts: {e}", exc_info=True)
        contracts = all_contracts

    existing_metadatas = {info.id: info.metadata for info in contracts}
    ids_and_versions = [{"id": info.id, "version": strip_version(info.version)} for info in contracts]

    chunk_size = settings.update_contracts_chunk_size
    start_index = 0

    while start_index < len(ids_and_versions):
        chunk = ids_and_versions[start_index : start_index + chunk_size]

        # Try JS interop first, fall back to algod on failure
        states = {}
        if settings.enable_js:
            try:
                states = await calljs("fetchContractsGlobalViews", contractType=type, idVersions=chunk)
            except Exception as e:
                logger.warning(f"JS interop failed for cache update ({type}), trying algod fallback: {e}")

        if not states:
            try:
                states = await fetch_contracts_views_batch(chunk)
            except Exception as e:
                logger.error(f"Algod fallback also failed for cache update ({type}): {e}")

        for s_id, state in states.items():
            id = int(s_id)
            old_metadata = existing_metadatas[id]
            if old_metadata is None:
                old_metadata = {}

            # Don't overwrite good cache with empty initial data
            new_initial = state.get("initial", {})
            old_cache = old_metadata.get("cache", {})
            old_initial = old_cache.get("initial", {})
            if not new_initial and old_initial:
                continue

            new_metadata = {**old_metadata, "cache": state}
            update_contract(id, metadata=new_metadata)

        start_index += chunk_size
        await asyncio.sleep(1)

    time_delta = datetime.now(UTC) - start_time
    logger.info(
        f"Updated state cache for {len(all_contracts)} contracts: {type} ({skipped} skipped) in {time_delta.total_seconds()}s"
    )


@safe_async_method
async def record_contracts_stats() -> None:
    logger.info("Making snapshot of contracts TVL...")
    farm_tvl = calculate_tvl_for_type(PoolType.FARM)
    distribution_tvl = calculate_tvl_for_type(PoolType.DISTRIBUTION)
    staking_tvl = calculate_tvl_for_type(PoolType.STAKING)
    save_snapshot(farm_tvl, distribution_tvl, staking_tvl)


@repeat_every(settings.contracts_cache_ttl)
async def update_contracts_worker():
    if not settings.update_contract_caches:
        logger.debug("Contract cache updates are disabled (UPDATE_CONTRACT_CACHES=false)")
        return
    logger.info("Updating contract caches...")
    await update_contracts_cache("farm")
    await update_contracts_cache("distribution")

    if settings.is_mainnet():
        await record_contracts_stats()

    logger.info("Contract caches updated.")


def sync_new_pools():
    if settings.sync_new_pools:
        logger.info("Started SYNC process.")
        asyncio.run(sync_pools_loop())


@repeat_every(settings.asset_prices_update_interval)
@safe_async_method
async def update_asset_prices_background():
    """Background task that updates asset prices with robust error handling."""
    if not settings.background_asset_prices_update:
        logger.info("Background asset price updates are disabled")
        return

    logger.info("Starting background asset price update")

    current_round = await asyncio.to_thread(get_current_round)

    all_assets = db.assets.get_all()

    # Exclude LP tokens — they are priced separately by update_lp_token_prices()
    try:
        lp_defs = await get_lp_token_definitions()
        lp_token_ids = {d["lp_token_id"] for d in lp_defs}
    except Exception:
        logger.exception(
            "LP token registry failed; skipping regular asset refresh to avoid overwriting derived LP prices",
        )
        lp_token_ids = None

    prioritized_assets = (
        [asset.id for asset in all_assets if asset.id not in lp_token_ids] if lp_token_ids is not None else []
    )
    random.shuffle(prioritized_assets)

    # Pre-fetch all existing prices in one MongoDB query (instead of N individual queries)
    existing_prices = {p.id: p for p in db.asset_prices.get_all()}

    total_updated = 0
    failures = 0
    skipped = 0

    cb = get_circuit_breaker("vestige_api")
    if not prioritized_assets:
        logger.info("No non-LP assets require a background price check")
    else:
        batch_size = min(
            settings.asset_price_update_batch_size,
            len(prioritized_assets),
        )
        for i in range(0, len(prioritized_assets), batch_size):
            batch = prioritized_assets[i : i + batch_size]
            batch_success = 0

            for asset_id in batch:
                asset_price = existing_prices.get(asset_id)
                if asset_price is not None and not is_asset_price_stale(asset_price):
                    skipped += 1
                    continue

                refresh = create_asset_price if asset_price is None else update_asset_price
                refresh_args = (asset_id, current_round) if asset_price is None else (asset_price, current_round)
                try:
                    await cb.execute(
                        with_exponential_backoff,
                        refresh,
                        *refresh_args,
                        max_retries=2,
                        retry_on=(PriceProviderUnavailableError,),
                        record_failure=lambda exc: isinstance(
                            exc,
                            PriceProviderUnavailableError,
                        ),
                    )
                    total_updated += 1
                    batch_success += 1
                except (CircuitOpenError, PriceRefreshError) as exc:
                    failures += 1
                    logger.warning("Price refresh failed for asset %s: %s", asset_id, exc)
                except Exception:
                    failures += 1
                    logger.exception("Unexpected price refresh failure for asset %s", asset_id)

            # Sleep between batches only (not per asset)
            if i + batch_size < len(prioritized_assets):
                delay = (
                    settings.asset_price_batch_delay * 2
                    if batch_success < len(batch) / 2
                    else settings.asset_price_batch_delay
                )
                await asyncio.sleep(delay)

    logger.info(
        "Asset price update completed: %s updated, %s skipped, %s failed",
        total_updated,
        skipped,
        failures,
    )

    # LP token prices: calculate from on-chain reserves
    try:
        await update_lp_token_prices(current_round)
    except Exception as e:
        logger.error(f"LP token price update failed: {e}")


def run_background():
    async def tasks():
        task_list = []

        if settings.migrate:
            task_list.append(asyncio.create_task(safe_background_task(migrate_background(), "migrate_background")))

        if settings.update_contract_caches:
            task_list.append(asyncio.create_task(safe_background_task(update_contracts_worker(), "update_contracts")))

        if settings.background_asset_prices_update:
            task_list.append(
                asyncio.create_task(safe_background_task(update_asset_prices_background(), "update_prices"))
            )

        if task_list:
            await asyncio.gather(*task_list, return_exceptions=True)
        else:
            logger.warning("No background tasks were configured to run")

    logger.info("Started background tasks.")
    asyncio.run(tasks())


@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    logger.info(f"Started background tasks process: {proc}")
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()


@contextmanager
def start_sync_proc():
    proc = spawn.Process(target=sync_new_pools)
    proc.start()
    logger.info(f"Started sync process: {proc}")
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()
