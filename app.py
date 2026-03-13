import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import List, Optional

import uvicorn
from algosdk import encoding
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

import dexes.humble as humble
import flex.api
from api import stats
from api.background import start_bg_tasks, start_sync_proc
from api.db_model import ContractType
from api.notifications import notify_new_pool
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, NftInfo
from blockchain.indexer import get_address_app_ids, get_address_app_ids_async
from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.db.contracts import ContractInfo, get_contract, get_contracts_by_type, update_contract, \
    insert_contract, invalidate_contracts_cache
from core.db.model import UserPool
from core.js_interop import calljs, managed_js_interop_server
from core.util import parse_bignum, strip_version
from core.auth import require_password
from env import settings
from flex.data.asset_prices import get_asset_price_not_cached
from flex.data.lp_states import create_lp_state_by_lp_token_id
from flex.data.pool_state import get_or_create_pool_state, update_pool_state
from flex.data.pool_state_priced import calculate_user_pool_state_cost
from flex.migrations import migrate_before_start
from flex.migrations.contracts import create_pool_from_contract
from flex.providers.vestige import get_dex_tag_by_name
from flex.sync_pools import get_sync_user_state_by_address

VERSION = '2.1.0'
app = FastAPI(
    title='Cometa',
    version=VERSION,
    description=f'Cometa API {VERSION}',
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=['https://app.cometa.farm', 'http://localhost:3000'],
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(flex.api.router)


# Catch-all exception handlers to ensure CORS headers are present on error responses.
# Without these, unhandled exceptions bypass CORSMiddleware and browsers block the response.
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

logger = logging.getLogger(__name__)
logging.getLogger('base').setLevel(logging.INFO)


# COMMON API

@app.get('/status', tags=['Common'])
async def status() -> dict:
    return {
        'version': VERSION,
        'algo_network': settings.algo_network
    }


# WALLET API

@app.get('/wallet/{address}/assets', tags=['Wallet'])
async def wallet_assets(address: str) -> list[AssetInfo]:
    loop = asyncio.get_running_loop()
    assets = await loop.run_in_executor(None, get_wallet_assets, address)
    return assets


@app.get('/wallet/{address}/total_cost/', tags=['Wallet'])
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> list[TimedCost]:
    return []


@app.get('/wallet/{address}/nfts', tags=['Wallet'])
async def wallet_nfts(address: str) -> list[NftInfo]:
    return []


@app.get('/wallet/{address}/pools', tags=['Wallet'])
async def wallet_pools(address: str, cached: bool = True) -> list[UserPool]:
    try:
        user_pools_state = await get_sync_user_state_by_address(address)
        if not user_pools_state or not user_pools_state.pool_by_address:
            logger.info(f"No pools found for address {address}")
            return []

        user_state_by_pool_id = {state.pool_id: state for state in user_pools_state.pool_by_address.values()}
        user_cost = await calculate_user_pool_state_cost(user_pools_state)

        user_pools = []
        for pool_id, pool_cost in user_cost.pools_by_id.items():
            if pool_id not in user_state_by_pool_id:
                logger.warning(f"Pool ID {pool_id} found in cost data but not in user state for {address}")
                continue

            user_state = user_state_by_pool_id[pool_id]
            user_pools.append(UserPool(
                pool_id=pool_id,
                name=pool_cost.pool_info.description,
                current_apr=pool_cost.pool_info.metadata.get('apr', 0) if pool_cost.pool_info.metadata else 0,
                staked_usd=pool_cost.staked_usd,
                reward_usd=pool_cost.reward_usd if hasattr(pool_cost, 'reward_usd') else 0,
                lock_timestamp=user_state.lock_timestamp if hasattr(user_state, 'lock_timestamp') else 0,
                ended_duration=user_state.ended_duration if hasattr(user_state, 'ended_duration') else None,
                staked_token_id=pool_cost.pool_info.stake_token.id,
                staked_tokens=user_state.staked_amount,
                staked_microtokens=user_state.staked_amount_micros,
                reward_token_id=pool_cost.pool_info.reward_token.id,
                last_updated=user_pools_state.updated
            ))
        return user_pools
    except Exception as e:
        logger.error(f"Error retrieving pools for address {address}: {e}", exc_info=True)
        return []


# CONTRACTS API

class AddContract(BaseModel):
    type: ContractType
    id: int = ...
    version: str
    description: Optional[str] = None
    metadata: Optional[dict] = None


def parse_cache(cache: Optional[dict]) -> dict:
    if cache is None:
        return {}

    try:
        begin_block = parse_bignum(cache['initial']['beginBlock'])
        end_block = parse_bignum(cache['initial']['endBlock'])
        lock_length_blocks = parse_bignum(cache['initial']['lockLengthBlocks'])

        current_time = datetime.now()
        current_block = get_current_round()

        return {
            'begin_block': begin_block,
            'end_block': end_block,
            'begin_date': date_from_block(begin_block, current_block, current_time),
            'end_date': date_from_block(end_block, current_block, current_time),
            'lock_length_blocks': lock_length_blocks,
        }
    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing cache: {e}", exc_info=True)
        return {}


async def create_contract(contract_info: AddContract, new_metadata: dict) -> ContractInfo:
    return await create_contract_with(
        type=contract_info.type,
        id=contract_info.id,
        version=contract_info.version,
        description=contract_info.description,
        metadata=new_metadata
    )


async def create_contract_with(type: str, id: int, version: str, description: str, metadata: dict) -> ContractInfo:
    try:
        cache = metadata.get('cache')
        metadata_fields = parse_cache(cache)
        current_date = datetime.now()

        if 'dex' in metadata:
            try:
                metadata['dex'] = get_dex_tag_by_name(metadata['dex'])
            except Exception as e:
                logger.warning(f"Could not get DEX tag for {metadata['dex']}: {e}")

        contract = ContractInfo(
            type=type,
            id=id,
            version=version,
            description=description,
            deployed_timestamp=current_date.timestamp(),
            deployed_date=current_date,
            begin_date=metadata_fields.get('begin_date'),
            end_date=metadata_fields.get('end_date'),
            metadata=metadata
        )
        insert_contract(contract)
        invalidate_contracts_cache()

        try:
            pool_info = await create_pool_from_contract(contract)
            if pool_info is not None:
                logger.info(f"Created pool info for contract {id}: {pool_info.id}")

                if 'dex' in metadata:
                    try:
                        await create_lp_state_by_lp_token_id(pool_info.stake_token.id)
                        logger.info(f"Created LP state for token {pool_info.stake_token.id}")
                    except Exception as e:
                        logger.error(f"Error creating LP state: {e}", exc_info=True)

                try:
                    pool_state = await get_or_create_pool_state(pool_info.id)
                    await update_pool_state(pool_state)
                    logger.info(f"Updated pool state for pool {pool_info.id}")
                except Exception as e:
                    logger.error(f"Error updating pool state: {e}", exc_info=True)

                try:
                    await get_asset_price_not_cached(pool_info.stake_token.id)
                    await get_asset_price_not_cached(pool_info.reward_token.id)
                    logger.info(f"Fetched asset prices for tokens {pool_info.stake_token.id} and {pool_info.reward_token.id}")
                except Exception as e:
                    logger.error(f"Error fetching asset prices: {e}", exc_info=True)
        except Exception as e:
            logger.error(f'Error creating pool from contract {id}: {e}', exc_info=True)

        return contract
    except Exception as e:
        logger.error(f"Fatal error creating contract {id}: {e}", exc_info=True)
        raise


@app.post('/contract/register', tags=['Contracts'])
async def register_contract(contract: AddContract) -> ContractInfo:
    logger.info(f'Registering a new contract {contract}')

    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    cache_metadata = {}

    if contract.type in ('farm', 'distribution'):
        global_views = await calljs("fetchContractsGlobalViews", contractType=contract.type,
                                    idVersions=[{'id': contract.id, 'version': strip_version(contract.version)}])
        if str(contract.id) not in global_views:
            raise HTTPException(status_code=409,
                                detail="Contract with given ID is not present in the network or does not match the given type")

        view = global_views[str(contract.id)]

        target_beneficiary = settings.beneficiary_address
        if not target_beneficiary:
            logger.warning("Beneficiary address not set in settings, skipping beneficiary check")
        else:
            target_beneficiary_hex = '0x' + encoding.decode_address(target_beneficiary).hex()
            contract_beneficiary = view['initial']['beneficiary']
            if contract_beneficiary != target_beneficiary_hex:
                raise HTTPException(status_code=403,
                                    detail=f"Farm's beneficiary address is invalid (expected {target_beneficiary}, got {contract_beneficiary})")

        cache_metadata = {"cache": view}

    metadata = {**contract.metadata, **cache_metadata} if contract.metadata is not None else cache_metadata
    logger.info(f'Registering a contract with metadata:\n{metadata}')
    rich_contract = await create_contract(contract, metadata)

    try:
        await notify_new_pool(
            begin_block=rich_contract.metadata['begin_block'],
            end_block=rich_contract.metadata['end_block'],
            lock_length_blocks=rich_contract.metadata['lock_length_blocks'],
            type=contract.type,
            metadata=contract.metadata,
        )
    except Exception as e:
        logger.error(f'Error notifying about new pool: {e}', exc_info=True)

    return rich_contract


@app.post('/contracts/refresh-cache', tags=['Contracts'], dependencies=[Depends(require_password)])
async def refresh_contracts_cache(
    contract_ids: Optional[List[int]] = None,
    type: Optional[ContractType] = None,
) -> dict:
    """Manually refresh metadata.cache for contracts by fetching live state from Algorand."""
    if not settings.enable_js:
        raise HTTPException(status_code=503, detail="JS interop is disabled")

    if contract_ids:
        contracts = [get_contract(cid) for cid in contract_ids]
        contracts = [c for c in contracts if c is not None]
    elif type:
        contracts = get_contracts_by_type(type)
    else:
        contracts = get_contracts_by_type(None)

    if not contracts:
        return {'refreshed': 0, 'errors': 0}

    by_type = {}
    for c in contracts:
        by_type.setdefault(c.type, []).append(c)

    refreshed = 0
    errors = 0
    for ctype, type_contracts in by_type.items():
        ids_and_versions = [{'id': c.id, 'version': strip_version(c.version)} for c in type_contracts]
        try:
            states = await calljs("fetchContractsGlobalViews", contractType=ctype, idVersions=ids_and_versions)
            for c in type_contracts:
                s_id = str(c.id)
                if s_id in states:
                    old_metadata = c.metadata or {}
                    new_metadata = {**old_metadata, "cache": states[s_id]}
                    update_contract(c.id, metadata=new_metadata)
                    refreshed += 1
                else:
                    logger.warning(f'refresh-cache: contract {c.id} not found in JS response')
                    errors += 1
        except Exception as e:
            logger.error(f'refresh-cache: failed for type {ctype}: {e}', exc_info=True)
            errors += len(type_contracts)

    invalidate_contracts_cache()
    return {'refreshed': refreshed, 'errors': errors}


@app.get('/contracts', tags=['Contracts'])
async def get_contracts(
        type: Optional[ContractType] = None,
        max_count: Optional[int] = None,
        new_first: bool = False,
        without_old_pools: bool = True,
        include_address_pools: Optional[str] = None
) -> List[ContractInfo]:
    contracts = get_contracts_by_type(type)

    if include_address_pools and (include_address_pools in settings.special_addresses or include_address_pools in settings.return_all_cometa_pools_to_addresses):
        logger.info(f'Including all pools for special address {include_address_pools}')
        return contracts

    if new_first:
        contracts.reverse()

    max_end_date = None
    if without_old_pools:
        max_end_date = datetime.now() - timedelta(days=settings.old_pool_end_date_days_ago)

    address_app_ids = list(settings.always_return_pool_ids)
    if settings.return_all_user_pools and include_address_pools is not None:
        try:
            user_state = await get_sync_user_state_by_address(include_address_pools)
            if user_state is not None:
                address_app_ids.extend([pool_state.pool_id for pool_state in user_state.pool_by_address.values()])
                logger.info(f'User {include_address_pools} has {len(address_app_ids)} pools in DB')
            else:
                fallback_ids = await get_address_app_ids_async(include_address_pools, only_active=True)
                address_app_ids.extend(fallback_ids)
                logger.info(f'No User Pools in DB, but {len(address_app_ids)} apps in network')
        except Exception as e:
            logger.error(f'Error fetching app ids for {include_address_pools}: {e}', exc_info=True)

    matching_pools = []
    for contract in contracts:
        if contract.id in address_app_ids:
            matching_pools.append(contract)
            continue
        if contract.end_date is None:
            matching_pools.append(contract)
            continue
        if without_old_pools:
            end_ts = contract.end_date.timestamp() if isinstance(contract.end_date, datetime) else float(contract.end_date)
            if end_ts < max_end_date.timestamp():
                continue
        matching_pools.append(contract)

    if max_count is not None and len(matching_pools) > max_count:
        matching_pools = matching_pools[:max_count]

    empty_cache_ids = [
        c.id for c in matching_pools
        if c.metadata is None or c.metadata.get('cache') is None
        or parse_bignum(c.metadata.get('cache', {}).get('global', {}).get('totalStaked', '0x0')) == 0
    ]
    if empty_cache_ids:
        logger.warning(f'Returning {len(empty_cache_ids)} pools with empty/zero cache: {empty_cache_ids[:10]}')

    return matching_pools


@app.get('/contracts/user/{address}', tags=['Contracts'])
async def get_user_contracts(
        address: str,
        type: Optional[ContractType] = None,
) -> List[ContractInfo]:
    """Get all Cometa contracts where user has local state (active + ended)."""
    user_app_ids = await get_address_app_ids_async(address, only_active=False)
    user_app_ids_set = set(user_app_ids)

    all_contracts = get_contracts_by_type(type) if type else get_contracts_by_type(None)
    cometa_ids = {c.id for c in all_contracts}
    user_cometa_ids = user_app_ids_set & cometa_ids

    return [c for c in all_contracts if c.id in user_cometa_ids]


# HUMBLE POOLS

@app.get('/humble/pool/{pool_id}', tags=['Humble'])
async def humble_pool_by_id(pool_id: int) -> Optional[humble.HumblePool]:
    try:
        pool = humble.get_pool_by_id(pool_id)
        if not pool:
            logger.info(f"Humble pool with ID {pool_id} not found")
        return pool
    except Exception as e:
        logger.error(f"Error fetching Humble pool {pool_id}: {e}", exc_info=True)
        return None


@app.get('/humble/pools', tags=['Humble'])
async def humble_pools_by_assets(assetA: int, assetB: int) -> List[humble.HumblePool]:
    pools = humble.get_pools_by_assets(assetA, assetB)
    if not pools:
        pools = humble.get_pools_by_assets(assetB, assetA)
    return pools


@app.get('/humble/pools/all', tags=['Humble'])
async def humble_pools_all() -> List[humble.HumblePool]:
    try:
        return humble.get_pools({})
    except Exception as e:
        logger.error(f"Error fetching Humble pools: {e}", exc_info=True)
        return []


# LOTTERY (disabled — returns 503)

@app.post('/lottery/swap', tags=['Lottery'])
async def nft_lottery_for_swap():
    return JSONResponse(status_code=503, content={"disabled": True})


@app.post('/lottery/staking', tags=['Lottery'])
async def nft_lottery_for_staking():
    return JSONResponse(status_code=503, content={"disabled": True})


@app.patch('/lottery/claim', tags=['Lottery'])
async def claim_prize_nft_for_swap():
    return JSONResponse(status_code=503, content={"disabled": True})


# STATS

@app.get('/stats/tvl', tags=['Stats'])
async def tvl() -> dict:
    return stats.get_tvl()


def setup_logging():
    logging.basicConfig(
        format=settings.logging_format,
        datefmt=settings.logging_date_format,
        level=settings.logging_level
    )
    logging.getLogger('aiocache.base').setLevel(logging.INFO)
    logging.getLogger('pymongo.serverSelection').setLevel(logging.INFO)
    logging.getLogger('pymongo.command').setLevel(logging.INFO)


setup_logging()


def init_app():
    """Initialize the application with migrations if needed"""
    if settings.migrate:
        logger.info("Running database migrations...")
        try:
            migrate_before_start()
            logger.info("Database migrations completed successfully")
        except Exception as e:
            logger.error(f"Error during database migrations: {e}", exc_info=True)
            raise

    # Ensure unique index on asset_prices.id and clean up corrupted data
    try:
        from flex import db as flex_db
        asset_prices_col = flex_db.asset_prices.mongodb_collection

        pipeline = [
            {'$group': {'_id': '$id', 'count': {'$sum': 1}, 'keep': {'$last': '$_id'}, 'all_ids': {'$push': '$_id'}}},
            {'$match': {'count': {'$gt': 1}}}
        ]
        duplicates = list(asset_prices_col.aggregate(pipeline))
        if duplicates:
            total_removed = 0
            for doc in duplicates:
                ids_to_remove = [oid for oid in doc['all_ids'] if oid != doc['keep']]
                result = asset_prices_col.delete_many({'_id': {'$in': ids_to_remove}})
                total_removed += result.deleted_count
            logger.info(f"Removed {total_removed} duplicate asset_prices entries")

        META_ASSET_ID = 923640017
        META_PRICE = 0.0035137119865087697
        corrupted = asset_prices_col.delete_many({
            'id': {'$ne': META_ASSET_ID},
            'price_algo': {'$gte': META_PRICE * 0.99, '$lte': META_PRICE * 1.01}
        })
        if corrupted.deleted_count > 0:
            logger.info(f"Cleaned {corrupted.deleted_count} corrupted asset prices (META price leak)")

        asset_prices_col.create_index('id', unique=True, name='id_unique')
        logger.info("Ensured unique index on asset_prices.id")

        # Add indexes for hot query patterns
        flex_db.lp_states.mongodb_collection.create_index('token_id', name='token_id_idx')
        flex_db.pool_states.mongodb_collection.create_index('pool_id', name='pool_id_idx')
        flex_db.user_states.mongodb_collection.create_index('address', name='address_idx')
        flex_db.lp_tokens.mongodb_collection.create_index('id', name='lp_token_id_idx')
        logger.info("Ensured indexes on lp_states.token_id, pool_states.pool_id, user_states.address, lp_tokens.id")
    except Exception as e:
        logger.error(f"Error during database index setup: {e}", exc_info=True)

    # Ensure all contracts have start/end dates populated
    try:
        contracts = get_contracts_by_type(None)
        needs_update = [c for c in contracts if c.end_date is None or c.begin_date is None]
        if needs_update:
            current_block = get_current_round()
            start_time = datetime.now()
            logger.info(f"Populating start/end dates for {len(needs_update)} contracts (block={current_block})...")
            for contract in needs_update:
                try:
                    metadata = contract.metadata
                    if metadata is None:
                        continue
                    cache = metadata.get('cache')
                    if cache is None:
                        continue

                    initial = cache.get('initial', {})
                    if contract.end_date is None:
                        end_block = metadata.get('end_block') or parse_bignum(initial.get('endBlock'))
                        if end_block:
                            metadata['end_block'] = end_block
                            contract.end_date = date_from_block(end_block, current_block, start_time)
                            metadata['end_date'] = contract.end_date

                    if contract.begin_date is None:
                        begin_block = metadata.get('begin_block') or parse_bignum(initial.get('beginBlock'))
                        if begin_block:
                            metadata['begin_block'] = begin_block
                            contract.begin_date = date_from_block(begin_block, current_block, start_time)
                            metadata['begin_date'] = contract.begin_date

                    from core.db.contracts import update_contract_with
                    update_contract_with(
                        contract_id=contract.id,
                        metadata=metadata,
                        begin_date=contract.begin_date,
                        end_date=contract.end_date
                    )
                except Exception as e:
                    logger.warning(f"Failed to update dates for contract {contract.id}: {e}")
            invalidate_contracts_cache()
            logger.info(f"Contract date migration completed for {len(needs_update)} contracts")
        else:
            logger.info("All contracts have start/end dates")
    except Exception as e:
        logger.error(f"Error during contract date migration: {e}", exc_info=True)


def start_app():
    """Start the application with all required services"""
    logger.info(f"Starting Cometa API v{VERSION} on port {settings.server_port} with {settings.workers_num} workers")

    try:
        if settings.enable_js:
            logger.info("Starting with JS interop server enabled")
            with managed_js_interop_server():
                with start_bg_tasks():
                    with start_sync_proc():
                        uvicorn.run(
                            "app:app",
                            host="0.0.0.0",
                            port=settings.server_port,
                            workers=settings.workers_num,
                            log_level=settings.uvicorn_log_level
                        )
        else:
            logger.info("Starting without JS interop server")
            with start_bg_tasks():
                with start_sync_proc():
                    uvicorn.run(
                        "app:app",
                        host="0.0.0.0",
                        port=settings.server_port,
                        workers=settings.workers_num,
                        log_level=settings.uvicorn_log_level
                    )
    except Exception as e:
        logger.error(f"Error starting application: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        init_app()
        start_app()
    except Exception as e:
        logger.critical(f"Fatal error during application startup: {e}", exc_info=True)
        sys.exit(1)
