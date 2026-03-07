import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import uvicorn
from algosdk import encoding
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

import dexes.humble as humble
import flex.api
from airdrop_all_active_stakers import snapshot_all
from api import stats
from api.background import start_bg_tasks, start_sync_proc
from api.db_model import ContractType
from api.migrations import update_contract_start_end_dates
from api.nft_lottery import lottery_for_swap, NftLottery, nft_lotteries, lottery_draws, NftPrize, lottery_for_staking, \
    LotteryDraw, send_all_prizes
from api.pool_snapshot import get_pool_snapshot
from api.swaps import SwapInfo, record_swap
from api.notifications import notify_new_pool
from api.wallet import send_nft
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, NftInfo
from blockchain.indexer import get_address_app_ids, get_address_app_ids_async
from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.cometa import fetch_user_pools
from core.db.cometa_users import get_address_pools
from core.db.contracts import ContractInfo, get_contract, get_contracts_by_type, get_active_contracts, remove_contract, \
    remove_contracts, update_contract, get_all_pool_contracts, insert_contract, invalidate_contracts_cache
from core.db.model import PoolStatus, PoolType, UserPool, PoolInfo
from core.db.pools import pools_db
from core.js_interop import calljs, start_js_interop_server
from core.util import parse_bignum, strip_version
from core.auth import require_password
from env import settings
from flex.blockchain.info import is_opted_in
from flex.data.asset_prices import get_asset_price_not_cached
from flex.data.lp_states import create_lp_state_by_lp_token_id
from flex.data.pool_state import get_or_create_pool_state, update_pool_state
from flex.data.pool_state_priced import calculate_user_pool_state_cost
from flex.migrations import migrate_before_start
from flex.migrations.contracts import create_pool_from_contract
from flex.providers.vestige import get_dex_tag_by_name
from flex.sync_pools import get_sync_user_state_by_address

VERSION = '2.0.3'
app = FastAPI(
    title='Cometa',
    version=VERSION,
    description=f'Cometa API {VERSION}'
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(flex.api.router)
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
    assets = get_wallet_assets(address)
    return assets


@app.get('/wallet/{address}/total_cost/', tags=['Wallet'])
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> list[TimedCost]:
    return get_wallet_total_cost(address, weeks_count)


@app.get('/wallet/{address}/nfts', tags=['Wallet'])
async def wallet_nfts(address: str) -> list[NftInfo]:
    return get_wallet_nfts(address)


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


@app.get('/wallet/{address}/pools/deprecated', tags=['Wallet'])
async def wallet_pools_deprecated(address: str, cached: bool = True) -> list[UserPool]:
    """
    Deprecated endpoint for fetching user pools.
    Use /wallet/{address}/pools instead.
    """
    if cached:
        return await get_address_pools(address)
    else:
        return await fetch_user_pools(address)


@app.get('/wallet/{address}/lottery-draws', tags=['Wallet'])
async def wallet_lottery_draws(address: str, win: Optional[bool] = None) -> list[LotteryDraw]:
    args = {'wallet': address}
    if win is not None:
        args['prize'] = {'$ne': None}
    return lottery_draws.get_many(args)


# CONTRACTS API

class AddContract(BaseModel):
    type: ContractType
    id: int = ...
    version: str
    description: Optional[str] = None
    metadata: Optional[dict] = None


class ModifyContract(BaseModel):
    # Type and version should not be changed
    id: int = ...
    description: Optional[str] = None
    metadata: Optional[dict] = None


def parse_cache(cache: Optional[dict]) -> dict:
    """
    Parse contract cache data to extract block and date information.

    Args:
        cache: The contract cache data containing block information

    Returns:
        dict: Parsed cache data with begin/end blocks, dates, and lock length
    """
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
    """
    Create a contract from AddContract model.

    Args:
        contract_info: Contract information from the AddContract model
        new_metadata: Metadata to use for the contract

    Returns:
        ContractInfo: The created contract
    """
    return await create_contract_with(
        type=contract_info.type,
        id=contract_info.id,
        version=contract_info.version,
        description=contract_info.description,
        metadata=new_metadata
    )


async def create_contract_with(type: str, id: int, version: str, description: str, metadata: dict) -> ContractInfo:
    """
    Create a contract with the given parameters and initialize related pool data.

    Args:
        type: Contract type
        id: Contract ID
        version: Contract version
        description: Contract description
        metadata: Contract metadata

    Returns:
        ContractInfo: The created contract
    """
    try:
        # Parse cache and prepare metadata
        cache = metadata.get('cache')
        metadata_fields = parse_cache(cache)
        current_date = datetime.now()

        if 'dex' in metadata:
            try:
                metadata['dex'] = get_dex_tag_by_name(metadata['dex'])
            except Exception as e:
                logger.warning(f"Could not get DEX tag for {metadata['dex']}: {e}")

        # Create and insert contract
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

        # Initialize pool data
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


@app.post('/contract/add', tags=['Contracts'], dependencies=[Depends(require_password)])
async def add_single_contract(contract: AddContract) -> ContractInfo:
    logger.info(f'Adding a new contract {contract}')

    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    created_contract = await create_contract(contract, contract.metadata)
    return created_contract


@app.post('/contracts/add', tags=['Contracts'], dependencies=[Depends(require_password)])
async def add_new_contracts(contracts: list[AddContract]) -> list[ContractInfo]:
    logger.info(f'Adding {len(contracts)} new contracts')

    created_contracts = []
    for contract in contracts:
        if get_contract(contract.id) is not None:
            logger.warning(f'Contract {contract.id} already exists')
        created_contract = await create_contract(contract, contract.metadata)
        created_contracts.append(created_contract)

    return created_contracts


# This method is NOT password-protected: it is intended to be used by users who add contracts themselves.
# The only thing we do here to ensure that our database isn't spammed with bullshit is checking that the contract
# really exists in the network, has a correct type and is fully deployed
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

        # Check that the contract's parameters are correct (beneficiary and creation fee are as we need them)
        # Get beneficiary address from settings
        target_beneficiary = settings.beneficiary_address
        if not target_beneficiary:
            logger.warning("Beneficiary address not set in settings, skipping beneficiary check")
        else:
            target_beneficiary_hex = '0x' + encoding.decode_address(target_beneficiary).hex()
            contract_beneficiary = view['initial']['beneficiary']
            if contract_beneficiary != target_beneficiary_hex:
                raise HTTPException(status_code=403,
                                    detail=f"Farm's beneficiary address is invalid (expected {target_beneficiary}, got {contract_beneficiary})")

        # Cache the contract's state right away so that user sees that it is displayed correctly right after
        # the contract is created even without connected wallet.
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


class DeployContract(BaseModel):
    type: ContractType
    settings: dict
    metadata: Optional[dict] = None
    description: Optional[str] = None


@app.post('/contract/deploy', tags=['Contracts'], dependencies=[Depends(require_password)])
async def deploy_contract(parameters: DeployContract) -> ContractInfo:
    logger.info(f'Deploying a new contract {parameters}')
    version = await calljs("contractVersion", contractType=parameters.type)
    contract_id = await calljs("deployContract", contractType=parameters.type, contractSettings=parameters.settings)
    created_contract = await create_contract_with(parameters.type, contract_id, version, parameters.description,
                                            parameters.metadata)

    await notify_new_pool(
        begin_block=parameters.settings['beginBlock'],
        end_block=parameters.settings['endBlock'],
        lock_length_blocks=parameters.settings['lockLengthBlocks'],
        type=parameters.type,
        metadata=parameters.metadata,
    )

    return created_contract


@app.patch('/contract/update', tags=['Contracts'], dependencies=[Depends(require_password)])
async def update(contract: ModifyContract) -> dict:
    logger.info(f'Updating contract {contract}')
    if get_contract(contract.id) is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    res = update_contract(contract.id, contract.description, contract.metadata)
    invalidate_contracts_cache()
    return {'updated': res}


@app.get('/contract/{contract_id}', tags=['Contracts'])
async def get_contract_by_id(contract_id: int) -> ContractInfo:
    contract = get_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@app.delete('/contract/{contract_id}', tags=['Contracts'], dependencies=[Depends(require_password)])
async def remove_contract_by_id(contract_id: int) -> dict:
    cnt = remove_contract(contract_id=contract_id)
    invalidate_contracts_cache()
    return {'deleted_count': cnt}


@app.get('/contracts/version', tags=['Contracts'])
async def get_contract_version(type: str) -> dict:
    version = await calljs("contractVersion", contractType=type)
    return {'version': version}


@app.get('/contracts/global_state', tags=['Contracts'])
async def get_contract_global_state(contract_id: int) -> dict:
    contract = get_contract(contract_id)
    global_views = await calljs("fetchContractsGlobalViews", contractType=contract.type,
                                idVersions=[{'id': contract.id, 'version': strip_version(contract.version)}])
    if str(contract.id) not in global_views:
        raise HTTPException(status_code=409,
                            detail="Contract with given ID is not present in the network or does not match the given type")

    return global_views[str(contract.id)]


@app.get('/contracts/local_state', tags=['Contracts'])
async def get_local_states(type: str, address: str) -> dict:
    contracts = get_contracts_by_type(type)
    if len(contracts) > 0:
        ids_and_versions = [{'id': info.id, 'version': strip_version(info.version)} for info in contracts]
        states = await calljs("fetchContractsLocalViews",
                              contractType=type,
                              idVersions=ids_and_versions,
                              walletAddress=address)
        return states
    return {}


@app.get('/contracts', tags=['Contracts'])
async def get_contracts(
        type: Optional[ContractType] = None,
        max_count: Optional[int] = None,
        new_first: bool = False,
        without_old_pools: bool = True,
        include_address_pools: Optional[str] = None
) -> List[ContractInfo]:
    """
    Get contracts filtered by type and other parameters.

    Args:
        type: Filter by contract type
        max_count: Maximum number of contracts to return
        new_first: Sort by newest first
        without_old_pools: Exclude old pools
        include_address_pools: Include only pools for this address
    """
    contracts = get_contracts_by_type(type)

    # Check if user address is in the special addresses list
    if include_address_pools and (include_address_pools in settings.special_addresses or include_address_pools in settings.return_all_cometa_pools_to_addresses):
        logger.info(f'Including all pools for special address {include_address_pools}')
        return contracts

    if new_first:
        contracts.reverse()

    max_end_date = None
    if without_old_pools:
        max_end_date = datetime.now(timezone.utc) - timedelta(days=settings.old_pool_end_date_days_ago)

    address_app_ids = list(settings.always_return_pool_ids)
    if settings.return_all_user_pools and include_address_pools is not None:
        try:
            user_state = await get_sync_user_state_by_address(include_address_pools)
            if user_state is not None:
                address_app_ids.extend([pool_state.pool_id for pool_state in user_state.pool_by_address.values()])
                logger.info(f'User {include_address_pools} has {len(address_app_ids)} pools in DB')
            else:
                address_app_ids.extend(get_address_app_ids(include_address_pools, only_active=True))
                logger.info(f'No User Pools in DB, but {len(address_app_ids)} apps in network')
        except Exception as e:
            logger.error(f'Error fetching app ids for {include_address_pools}: {e}', exc_info=True)

    # TODO: move as arg to DB query
    matching_pools = []
    for contract in contracts:
        if contract.id in address_app_ids:
            matching_pools.append(contract)
            continue
        if contract.end_date is None:
            matching_pools.append(contract)
            continue
        if without_old_pools and contract.end_date < max_end_date:
            continue
        matching_pools.append(contract)

    if max_count is not None and len(matching_pools) > max_count:
        matching_pools = matching_pools[:max_count]

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


@app.delete('/contracts', tags=['Contracts'], dependencies=[Depends(require_password)])
async def remove_contracts_by_type(type: str) -> dict:
    cnt = remove_contracts(type=type)
    invalidate_contracts_cache()
    return {'deleted_count': cnt}


# POOLS API

@app.get('/pools', tags=['Pools'])
async def get_pools_by_type_or_status(
        type: Optional[PoolType] = None,
        status: Optional[PoolStatus] = None
) -> List[PoolInfo]:
    args = {}
    if type:
        args['type'] = type
    if status:
        args['status'] = status
    return pools_db.get_many(args)


@app.patch('/pools/verify', tags=['Pools'], dependencies=[Depends(require_password)])
async def verify_pool(pool_id: int) -> str:
    contract = get_contract(pool_id)
    if contract.metadata.get('verified'):
        return 'Already verified!'
    new_metadata = {**contract.metadata, 'verified': True}
    update_contract(pool_id, metadata=new_metadata)
    invalidate_contracts_cache()
    return 'Success!'


@app.get('/pools/snapshot', tags=['Pools'], dependencies=[Depends(require_password)])
async def make_pool_snapshot(pool_id: int, max_round: Optional[int] = None) -> dict:
    wallets = get_pool_snapshot(pool_id, max_round)
    return dict(sorted(wallets.items()))


@app.get('/pools/snapshot_all', tags=['Pools'], dependencies=[Depends(require_password)])
async def make_all_pools_snapshot(max_round: Optional[int] = None) -> dict:
    wallets = snapshot_all()
    return wallets


@app.post('/pools/notify', tags=['Pools'], dependencies=[Depends(require_password)])
async def handle_pools_notify_social_channels(pool_id: int) -> None:

    contract = get_contract(pool_id)
    if contract is None:
        raise HTTPException(status_code=404, detail='Contract not found')

    await notify_new_pool(
        begin_block=contract.metadata['begin_block'],
        end_block=contract.metadata['end_block'],
        lock_length_blocks=contract.metadata['lock_length_blocks'],
        type=contract.type,
        metadata=contract.metadata,
    )
    return None


# HUMBLE POOLS

@app.get('/humble/pool/{pool_id}', tags=['Humble'])
async def humble_pool_by_id(pool_id: int) -> Optional[humble.HumblePool]:
    """
    Get Humble pool by ID.

    Args:
        pool_id: The ID of the pool to retrieve

    Returns:
        Optional[humble.HumblePool]: The Humble pool if found, None otherwise
    """
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
    """
    Get Humble pools by asset pair.

    This endpoint tries both asset orders to find pools.
    """
    # Try both asset orders to find pools
    pools = humble.get_pools_by_assets(assetA, assetB)

    # If no pools found with the original order, try the reverse order
    if not pools:
        pools = humble.get_pools_by_assets(assetB, assetA)

    return pools


@app.get('/humble/pools/all', tags=['Humble'])
async def humble_pools_all() -> List[humble.HumblePool]:
    """
    Get all Humble pools.

    Returns:
        List[humble.HumblePool]: List of all Humble pools
    """
    try:
        return humble.get_pools({})
    except Exception as e:
        logger.error(f"Error fetching Humble pools: {e}", exc_info=True)
        return []


# LOTTERY

@app.post('/lottery/swap', tags=['Lottery'])
async def nft_lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    # TODO: check swap already recorded

    record_swap(swap)
    return lottery_for_swap(swap)


@app.post('/lottery/staking', tags=['Lottery'])
async def nft_lottery_for_staking(address: str, pool_id: int) -> Optional[NftPrize]:
    return await lottery_for_staking(pool_id, address)


@app.post('/lottery/new', tags=['Lottery'], dependencies=[Depends(require_password)])
async def create_a_new_nft_lottery(lottery: NftLottery) -> None:
    if nft_lotteries.get_by_primary_key(lottery.name) is not None:
        raise HTTPException(status_code=409, detail='Lottery with such name already exists')
    nft_lotteries.create(lottery)


@app.post('/lottery/update', tags=['Lottery'], dependencies=[Depends(require_password)])
async def update_nft_lottery(lottery: NftLottery) -> None:
    if nft_lotteries.get_by_primary_key(lottery.name) is None:
        raise HTTPException(status_code=404, detail=f'Lottery with name {lottery.name} not found')
    nft_lotteries.update(lottery)


@app.patch('/lottery/claim', tags=['Lottery'])
async def claim_prize_nft_for_swap(wallet: str) -> dict:
    """
    Claim a lottery prize NFT for the given wallet address.

    Args:
        wallet: The wallet address to claim the prize for

    Returns:
        dict: Status of the claim operation
    """
    logger.info(f'Claiming lottery prize for {wallet}')

    # Find unclaimed wins for the wallet
    wins = lottery_draws.get_many({'wallet': wallet, 'claimed': False, 'prize': {'$ne': None}})
    logger.info(f'Found {len(wins)} unclaimed lottery wins for {wallet}')

    if len(wins) == 0:
        raise HTTPException(status_code=404, detail=f'No unclaimed lottery prizes found for {wallet}')

    # Get the most recent win
    lottery_draw = wins[-1]
    logger.info(f'Processing lottery draw: {lottery_draw}')

    result = {
        'success': False,
        'prize_id': lottery_draw.prize,
        'draw_id': str(lottery_draw.id) if hasattr(lottery_draw, 'id') else None
    }

    try:
        # Wait for opt-in confirmation with timeout
        start_time = datetime.now()
        opt_in_confirmed = False

        while datetime.now() - start_time < timedelta(seconds=9):  # 3 blocks timeout
            if is_opted_in(wallet, lottery_draw.prize):
                opt_in_confirmed = True
                logger.info(f'Opt-in confirmed for {wallet} to asset {lottery_draw.prize}')
                break
            await asyncio.sleep(1)

        if not opt_in_confirmed:
            logger.error(f'Opt-in for {wallet} to asset {lottery_draw.prize} is not confirmed within timeout')
            result['error'] = 'Opt-in not confirmed within timeout'
            lottery_draw.send_error = 'Opt-in not confirmed within timeout'
            lottery_draws.update(lottery_draw)
            return result

        # Send the NFT
        send_nft(lottery_draw.wallet, lottery_draw.prize)
        logger.info(f'NFT {lottery_draw.prize} sent to {wallet}')

        # Mark as claimed
        lottery_draw.claimed = True
        result['success'] = True

        # Remove from available NFTs in lotteries
        lotteries = nft_lotteries.get_all()
        for lottery in lotteries:
            if lottery_draw.prize in lottery.available_nfts:
                lottery.available_nfts.remove(lottery_draw.prize)
                nft_lotteries.update(lottery)
                logger.info(f'Removed NFT {lottery_draw.prize} from available NFTs in lottery {lottery.name}')

    except Exception as e:
        error_msg = f'Error sending NFT to {wallet}: {str(e)}'
        lottery_draw.send_error = error_msg
        logger.error(error_msg, exc_info=True)
        result['error'] = str(e)

    # Update the lottery draw record
    lottery_draws.update(lottery_draw)
    return result


@app.get('/lotteries/', tags=['Lottery'], dependencies=[Depends(require_password)])
async def get_lotteries() -> List[NftLottery]:
    return nft_lotteries.get_all()


@app.get('/lotteries/resend', tags=['Lottery'], dependencies=[Depends(require_password)])
async def resend_prizes() -> dict:
    return send_all_prizes()


# Overall Statistics

@app.get('/stats/tvl', tags=['Stats'])
async def tvl() -> dict:
    return stats.get_tvl()


@app.get('/stats/app-ids', tags=['Stats'], dependencies=[Depends(require_password)])
async def handle_address_app_ids(address: str, only_active: bool = False) -> dict:
    app_ids = get_address_app_ids(address, only_active)
    contracts = get_all_pool_contracts()
    user_pools = []
    for contract in contracts:
        if contract.id in app_ids:
            user_pools.append({'id': contract.id, 'description': contract.description})
    return {'app_ids': app_ids, 'user_pools': user_pools}


def setup_logging():
    logging.basicConfig(
        format=settings.logging_format,
        datefmt=settings.logging_date_format,
        level=settings.logging_level
    )
    logging.getLogger('aiocache.base').setLevel(logging.INFO)
    logging.getLogger('pymongo.serverSelection').setLevel(logging.INFO)
    logging.getLogger('pymongo.command').setLevel(logging.INFO)


# Setup logging
setup_logging()

# Initialize the application
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

# Start the application
def start_app():
    """Start the application with all required services"""
    logger.info(f"Starting Cometa API v{VERSION} on port {settings.server_port} with {settings.workers_num} workers")

    try:
        if settings.enable_js:
            logger.info("Starting with JS interop server enabled")
            with start_js_interop_server():
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
