import logging
import secrets
import sys
from datetime import datetime, timedelta
from time import sleep
from typing import List, Optional

import uvicorn
from algosdk import encoding
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import core
import dexes.humble as humble
import flex.api
from airdrop_all_active_stakers import snapshot_all
from api import stats
from api.background import start_bg_tasks
from api.db_model import ContractType
from api.migrations import update_contract_start_end_dates
from api.nft_lottery import lottery_for_swap, NftLottery, nft_lotteries, lottery_draws, NftPrize, lottery_for_staking, \
    LotteryDraw, send_all_prizes
from api.pool_snapshot import get_pool_snapshot
from api.swaps import SwapInfo, record_swap
from api.notifications import notify_new_pool
from api.wallet import send_nft
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, NftInfo
from blockchain.indexer import get_address_app_ids
from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.cometa import fetch_user_pools
from core.constants import LOG_FORMAT, LOG_DATE_FORMAT
from core.db.cometa_users import get_address_pools
from core.db.contracts import ContractInfo, get_contract, add_contract, get_contracts_by_type, remove_contract, \
    remove_contracts, update_contract, get_all_pool_contracts, insert_contract
from core.db.model import PoolStatus, PoolType, UserPool, PoolInfo
from core.db.pools import pools_db
from core.js_interop import calljs, start_js_interop_server
from core.util import parse_bignum, strip_version
from env import settings

VERSION = '1.9.3'
app = FastAPI(
    title='Cometa',
    version=VERSION,
    description=f'Cometa API {VERSION}'
)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(flex.api.router)
logger = logging.getLogger(__name__)


def check_password(password: str) -> None:
    if not secrets.compare_digest(settings.api_password, password):
        raise HTTPException(status_code=401, detail='Invalid password')


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
    if cached:
        return await get_address_pools(address)
    else:
        return await fetch_user_pools(address)


@app.get('/wallet/{address}/lottery-draws', tags=['Wallet'])
async def wallet_pools(address: str, win: Optional[bool] = None) -> list[LotteryDraw]:
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


@app.post('/contract/add', tags=['Contracts'])
async def add_new_contract(contract: AddContract, password: str) -> dict:
    logger.info(f'Adding a new contract {contract}')

    check_password(password)
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    added = add_contract(contract.type, contract.id, contract.version, contract.description, contract.metadata)
    return {'internal_id': added}


def parse_cache(cache: Optional[dict]) -> dict:
    if cache is None:
        return {}

    begin_block = parse_bignum(cache['initial']['beginBlock'])
    end_block = parse_bignum(cache['initial']['endBlock'])
    current_time = datetime.now()
    current_block = get_current_round()
    return {
        'begin_block': begin_block,
        'end_block': end_block,
        'begin_date': date_from_block(begin_block, current_block, current_time),
        'end_date': date_from_block(end_block, current_block, current_time),
        'lock_length_blocks': parse_bignum(cache['initial']['lockLengthBlocks']),
    }


def create_contract(contract_info: AddContract, new_metadata: dict) -> ContractInfo:
    cache = new_metadata.get('cache')
    metadata_fields = parse_cache(cache)
    current_date = datetime.now()
    contract = ContractInfo(
        type=contract_info.type,
        id=contract_info.id,
        version=contract_info.version,
        description=contract_info.description,
        deployed_timestamp=current_date.timestamp(),
        deployed_date=current_date,
        begin_date=metadata_fields.get('begin_date'),
        end_date=metadata_fields.get('end_date'),
        metadata=new_metadata
    )
    insert_contract(contract)
    return contract


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
        # Assuming that beneficiary address is our account stored in ALGO_MNEMONIC variable

        target_beneficiary = 'METAFG5UBD74CKQFIIABWMMQXR45J7BAP3KV6BVR3V7LDPNAEKNEVLMBRE'  # cometa.algo
        target_beneficiary_hex = '0x' + encoding.decode_address(target_beneficiary).hex()
        target_flat_algo_creation_fee = settings.farm_flat_algo_creation_fee * 1000000  # in microtokens

        contract_beneficiary = view['initial']['beneficiary']
        if contract_beneficiary != target_beneficiary_hex:
            raise HTTPException(status_code=403,
                                detail=f"Farm's beneficiary address is invalid (expected {target_beneficiary}, got {contract_beneficiary}")

        if parse_bignum(view['initial']['flatAlgoCreationFee']) != target_flat_algo_creation_fee:
            raise HTTPException(status_code=403,
                                detail=f"Farm's flat algo creation fee is invalid (expected {target_flat_algo_creation_fee})")

        # Cache the contract's state right away so that user sees that it is displayed correctly right after
        # the contract is created even without connected wallet.
        cache_metadata = {"cache": view}

    metadata = {**contract.metadata, **cache_metadata} if contract.metadata is not None else cache_metadata
    logger.info(f'Registering a contract with metadata:\n{metadata}')
    rich_contract = create_contract(contract, metadata)

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


@app.post('/contract/deploy', tags=['Contracts'])
async def deploy_contract(password: str, parameters: DeployContract) -> dict:
    logger.info(f'Deploying a new contract {parameters}')

    check_password(password)
    version = await calljs("contractVersion", contractType=parameters.type)
    contract_id = await calljs("deployContract", contractType=parameters.type, contractSettings=parameters.settings)
    internal_id = add_contract(parameters.type, contract_id, version, parameters.description, parameters.metadata)

    await notify_new_pool(
        begin_block=parameters.settings['beginBlock'],
        end_block=parameters.settings['endBlock'],
        lock_length_blocks=parameters.settings['lockLengthBlocks'],
        type=parameters.type,
        metadata=parameters.metadata,
    )

    return {'internal_id': internal_id}


@app.patch('/contract/update', tags=['Contracts'])
async def update(contract: ModifyContract, password: str) -> dict:
    logger.info(f'Updating contract {contract}')

    check_password(password)
    if get_contract(contract.id) is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    res = update_contract(contract.id, contract.description, contract.metadata)
    return {'updated': res}


@app.get('/contract/{contract_id}', tags=['Contracts'])
async def get_contract_by_id(contract_id: int) -> ContractInfo:
    contract = get_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@app.delete('/contract/{contract_id}', tags=['Contracts'])
async def remove_contract_by_id(contract_id: int, password: str) -> dict:
    check_password(password)
    cnt = remove_contract(contract_id=contract_id)
    return {'deleted_count': cnt}


@app.get('/contracts/version', tags=['Contracts'])
async def get_contract_version(type: str) -> dict:
    version = await calljs("contractVersion", contractType=type)
    return {'version': version}


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
    contracts = get_contracts_by_type(type)
    if new_first:
        contracts.reverse()

    max_end_date = None
    if without_old_pools:
        max_end_date = datetime.now() - timedelta(days=settings.old_pool_end_date_days_ago)

    address_app_ids = []
    if include_address_pools is not None:
        address_app_ids = get_address_app_ids(include_address_pools, only_active=True)

    # TODO: move as arg to DB query
    matching_pools = []
    for contract in contracts:
        if contract.id in address_app_ids:
            matching_pools.append(contract)
            continue
        if contract.end_date is None:
            # TODO: move method to proper file from migrations
            updated_contract = update_contract_start_end_dates(contract)
            if updated_contract is None:
                logger.warning(f'{contract.id} has no end date: {contract.format_str()}')
                continue
            contract = updated_contract
            logger.info(f'Updated contract {contract.id} with end date {contract.end_date}')
        if without_old_pools and contract.end_date < max_end_date:
            continue
        matching_pools.append(contract)

    if max_count is not None and len(matching_pools) > max_count:
        matching_pools = matching_pools[:max_count]

    return matching_pools


@app.delete('/contracts', tags=['Contracts'])
async def remove_contracts_by_type(type: str, password: str) -> dict:
    check_password(password)
    cnt = remove_contracts(type=type)
    return {'deleted_count': cnt}


# POOLS API

@app.get('/pools', tags=['Pools'])
async def get_pools_by_type_or_status(type: Optional[PoolType] = None, status: Optional[PoolStatus] = None) -> List[PoolInfo]:
    args = {}
    if type:
        args['type'] = type
    if status:
        args['status'] = status
    return pools_db.get_many(args)


@app.patch('/pools/verify', tags=['Pools'])
async def verify_pool(pool_id: int, password: str) -> str:
    check_password(password)
    contract = get_contract(pool_id)
    if contract.metadata.get('verified'):
        return 'Already verified!'
    new_metadata = {**contract.metadata, 'verified': True}
    update_contract(pool_id, metadata=new_metadata)
    return 'Success!'


@app.get('/pools/snapshot', tags=['Pools'])
async def make_pool_snapshot(password: str, pool_id: int, max_round: Optional[int] = None) -> dict:
    if password != 'YouShallNotPass':
        raise HTTPException(status_code=403, detail="Wrong password bro.")
    wallets = get_pool_snapshot(pool_id, max_round)
    return dict(sorted(wallets.items()))


@app.get('/pools/snapshot_all', tags=['Pools'])
async def make_pool_snapshot(password: str, max_round: Optional[int] = None) -> dict:
    if password != 'YouShallNotPass':
        raise HTTPException(status_code=403, detail="Wrong password bro.")
    wallets = snapshot_all()
    return wallets


@app.post('/pools/notify', tags=['Pools'])
async def handle_pools_notify_social_channels(password: str, pool_id: int) -> None:
    check_password(password)

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
    return humble.get_pool_by_id(pool_id)


@app.get('/humble/pools', tags=['Humble'])
async def humble_pools_by_assets(assetA: int, assetB: int) -> List[humble.HumblePool]:
    # FIXME: just don't ask me please ever
    if assetA == 796425061 and assetB == 1138500612:
        return humble.get_pools_by_assets(assetB, assetA)
    return humble.get_pools_by_assets(assetA, assetB)


@app.get('/humble/pools/all', tags=['Humble'])
async def humble_pools_all() -> List[humble.HumblePool]:
    return humble.get_pools({})


# LOTTERY

@app.post('/lottery/swap', tags=['Lottery'])
async def nft_lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    # TODO: check swap already recorded

    record_swap(swap)
    return lottery_for_swap(swap)


@app.post('/lottery/staking', tags=['Lottery'])
async def nft_lottery_for_staking(address: str, pool_id: int) -> Optional[NftPrize]:
    return await lottery_for_staking(pool_id, address, settings.is_mainnet())


@app.post('/lottery/new', tags=['Lottery'])
async def create_a_new_nft_lottery(lottery: NftLottery, password: str) -> None:
    check_password(password)
    if nft_lotteries.get_by_primary_key(lottery.name) is not None:
        raise HTTPException(status_code=409, detail='Lottery with such name already exists')
    nft_lotteries.create(lottery)


@app.post('/lottery/update', tags=['Lottery'])
async def update_nft_lottery(lottery: NftLottery, password: str) -> None:
    check_password(password)
    if nft_lotteries.get_by_primary_key(lottery.name) is None:
        raise HTTPException(status_code=404, detail=f'Lottery with name {lottery.name} not found')
    nft_lotteries.update(lottery)


@app.patch('/lottery/claim', tags=['Lottery'])
async def claim_prize_nft_for_swap(wallet: str) -> None:
    wins = lottery_draws.get_many({'wallet': wallet, 'claimed': False, 'prize': {'$ne': None}})

    logger.info(f'Lottery wins for {wallet}: {wins}')

    if len(wins) == 0:
        raise HTTPException(status_code=404, detail=f'Lottery draws for {wallet} are not found')
    lottery_draw = wins[-1]

    try:
        # to opt-in to go through
        sleep(5)
        send_nft(lottery_draw.wallet, lottery_draw.prize)
        lottery_draw.claimed = True

        lottery = nft_lotteries.get_by_primary_key(lottery_draw.lottery_name)
        lottery.available_nfts.remove(lottery_draw.prize)
        nft_lotteries.update(lottery)
    except Exception as e:
        lottery_draw.send_error = str(e)
        logger.error(f'Error sending NFT to {wallet}: {e}')

    lottery_draws.update(lottery_draw)


@app.get('/lotteries/', tags=['Lottery'])
async def get_lotteries(password: str) -> List[NftLottery]:
    check_password(password)
    return nft_lotteries.get_all()


@app.get('/lotteries/resend', tags=['Lottery'])
async def resend_prizes(password: str) -> dict:
    check_password(password)
    return send_all_prizes()


# Overall Statistics

@app.get('/stats/tvl', tags=['Stats'])
async def tvl() -> dict:
    return stats.get_tvl()


@app.get('/stats/app-ids', tags=['Stats'])
async def address_app_ids(password: str, address: str, only_active: bool = False) -> dict:
    check_password(password)
    app_ids = get_address_app_ids(address, only_active)
    contracts = get_all_pool_contracts()
    user_pools = []
    for contract in contracts:
        if contract.id in app_ids:
            user_pools.append({'id': contract.id, 'description': contract.description})
    return {'app_ids': app_ids, 'user_pools': user_pools}


def setup_logging():
    logging.basicConfig(
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=settings.logging_level
    )


setup_logging()


if __name__ == "__main__":
    argv = sys.argv[1:]

    if settings.enable_js:
        with start_js_interop_server():
            with start_bg_tasks():
                uvicorn.run("app:app", host="0.0.0.0", port=settings.server_port, workers=settings.workers_num)
    else:
        with start_bg_tasks():
            uvicorn.run("app:app", host="0.0.0.0", port=settings.server_port, workers=settings.workers_num)
