import logging
import secrets
import sys
from typing import List, Optional

import uvicorn
from algosdk import account, mnemonic, encoding
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from uvicorn.logging import ColourizedFormatter

import dexes.humble as humble
from airdrop import airdrop, snapshot
from api import stats
from api.background import start_bg_tasks
from api.nft_lottery import lottery_for_swap, NftLottery, nft_lotteries, lottery_draws, NftPrize, lottery_for_staking, \
    LotteryDraw, send_all_prizes
from api.swaps import SwapInfo, record_swap
from api.wallet import send_nft
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, NftInfo
from core.cometa import fetch_user_pools
from core.constants import LOG_FORMAT, LOG_DATE_FORMAT
from core.db.cometa_users import get_address_pools
from core.db.contracts import ContractInfo, get_contract, add_contract, get_contracts_by_type, remove_contract, \
    remove_contracts, update_contract
from core.db.migrations.separate_user_info import migrate
from core.db.model import PoolStatus, PoolType, UserPool, PoolInfo
from core.db.pools import pools_db
from core.js_interop import calljs, start_js_interop_server
from core.util import parse_bignum, strip_version
from env import settings

VERSION = '0.2.0'
app = FastAPI(
    title='Cometa',
    version=VERSION,
    description=f'Cometa API {VERSION}'
)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        'https://app.cometa.farm/meta-dao',
        '*'
    ],
    allow_methods=['*'],
    allow_headers=['*'],
)


def check_password(password: str) -> None:
    if not secrets.compare_digest(settings.api_password, password):
        raise HTTPException(status_code=401, detail="Invalid password")


@app.get('/status')
async def status() -> dict:
    return {
        'version': VERSION,
        'algo_network': settings.algo_network
    }


@app.get('/wallet/{address}/assets')
async def wallet_assets(address: str) -> list[AssetInfo]:
    assets = get_wallet_assets(address)
    return assets


@app.get('/wallet/{address}/total_cost/')
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> list[TimedCost]:
    return get_wallet_total_cost(address, weeks_count)


@app.get('/wallet/{address}/nfts')
async def wallet_nfts(address: str) -> list[NftInfo]:
    return get_wallet_nfts(address)


@app.get('/wallet/{address}/pools')
async def wallet_pools(address: str, cached: bool = True) -> list[UserPool]:
    if cached:
        return await get_address_pools(address)
    else:
        return await fetch_user_pools(address)


@app.get('/wallet/{address}/lottery-draws')
async def wallet_pools(address: str, win: Optional[bool] = None) -> list[LotteryDraw]:
    args = {'wallet': address}
    if win is not None:
        args['prize'] = {'$ne': None}
    return lottery_draws.get_many(args)


class AddContract(BaseModel):
    type: str
    id: int = ...
    version: str
    description: Optional[str] = None
    metadata: Optional[dict] = None


class ModifyContract(BaseModel):
    # Type and version should not be changed
    id: int = ...
    description: Optional[str] = None
    metadata: Optional[dict] = None


@app.post('/contract/add')
async def add_new_contract(contract: AddContract, password: str) -> dict:
    check_password(password)
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    added = add_contract(contract.type, contract.id, contract.version, contract.description, contract.metadata)
    return {'internal_id': added}


# This method is NOT password-protected: it is intended to be used by users who add contracts themselves.
# The only thing we do here to ensure that our database isn't spammed with bullshit is checking that the contract
# really exists in the network, has a correct type and is fully deployed
@app.post('/contract/register')
async def register_contract(contract: AddContract) -> None:
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    cache_metadata = {}

    # TODO: check for LaaS contracts
    if contract.type in ('farm', 'distribution'):
        global_views = await calljs("fetchContractsGlobalViews", contractType=contract.type,
                                    idVersions=[{'id': contract.id, 'version': strip_version(contract.version)}])
        if str(contract.id) not in global_views:
            raise HTTPException(status_code=409,
                                detail="Contract with given ID is not present in the network or does not match the given type")

        view = global_views[str(contract.id)]

        # Check that the contract's parameters are correct (beneficiary and creation fee are as we need them)
        # Assuming that beneficiary address is our account stored in ALGO_MNEMONIC variable
        target_beneficiary = account.address_from_private_key(mnemonic.to_private_key(settings.algo_mnemonic))
        target_beneficiary_hex = '0x' + encoding.decode_address(target_beneficiary).hex()
        target_creation_fee = settings.farm_creation_fee
        target_flat_algo_creation_fee = settings.farm_flat_algo_creation_fee * 1000000  # in microtokens

        contract_beneficiary = view['initial']['beneficiary']
        if contract_beneficiary != target_beneficiary_hex:
            raise HTTPException(status_code=403,
                                detail=f"Farm's beneficiary address is invalid (expected {target_beneficiary}, got {contract_beneficiary}")

        if parse_bignum(view['initial']['creationFee']) != target_creation_fee:
            raise HTTPException(status_code=403,
                                detail=f"Farm's creation fee is invalid (expected {target_creation_fee}")

        if parse_bignum(view['initial']['flatAlgoCreationFee']) != target_flat_algo_creation_fee:
            raise HTTPException(status_code=403,
                                detail=f"Farm's flat algo creation fee is invalid (expected {target_flat_algo_creation_fee})")

        # Cache the contract's state right away so that user sees that it is displayed correctly right after
        # the contract is created even without connected wallet.
        cache_metadata = {"cache": view}

    metadata = cache_metadata if contract.metadata is None else {**contract.metadata, **cache_metadata}
    add_contract(contract.type, contract.id, contract.version, contract.description, metadata)


class DeployContract(BaseModel):
    type: str
    settings: dict
    metadata: Optional[dict] = None
    description: Optional[str] = None


@app.post('/contract/deploy')
async def deploy_contract(password: str, parameters: DeployContract) -> dict:
    check_password(password)
    version = await calljs("contractVersion", contractType=parameters.type)
    contract_id = await calljs("deployContract", contractType=parameters.type, contractSettings=parameters.settings)
    added = add_contract(parameters.type, contract_id, version, parameters.description, parameters.metadata)
    return {'internal_id': added}


@app.patch('/contract/update')
async def update(contract: ModifyContract, password: str) -> dict:
    check_password(password)
    if get_contract(contract.id) is None:
        raise HTTPException(status_code=404, detail="Contract not found")

    res = update_contract(contract.id, contract.description, contract.metadata)
    return {'updated': res}


@app.get('/contract/{contract_id}')
async def get_contract_by_id(contract_id: int) -> ContractInfo:
    contract = get_contract(contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@app.delete('/contract/{contract_id}')
async def remove_contract_by_id(contract_id: int, password: str) -> dict:
    check_password(password)
    cnt = remove_contract(contract_id=contract_id)
    return {'deleted_count': cnt}


@app.get('/contracts/version')
async def get_contract_version(type: str) -> dict:
    version = await calljs("contractVersion", contractType=type)
    return {'version': version}


@app.get('/contracts/local_state')
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


@app.get('/contracts')
async def get_contracts(type: str) -> List[ContractInfo]:
    return get_contracts_by_type(type)


@app.delete('/contracts')
async def remove_contracts_by_type(type: str, password: str) -> dict:
    check_password(password)
    cnt = remove_contracts(type=type)
    return {'deleted_count': cnt}


# POOLS

@app.get('/pools')
async def get_pools_by_type_or_status(type: Optional[PoolType] = None, status: Optional[PoolStatus] = None) -> List[PoolInfo]:
    args = {}
    if type:
        args['type'] = type
    if status:
        args['status'] = status
    return pools_db.get_many(args)


@app.patch('/pools/verify')
async def verify_pool(pool_id: int, password: str) -> str:
    check_password(password)
    contract = get_contract(pool_id)
    if contract.metadata.get('verified'):
        return 'Already verified!'
    new_metadata = {**contract.metadata, 'verified': True}
    update_contract(pool_id, metadata=new_metadata)
    return 'Success!'


# HUMBLE POOLS

@app.get('/humble/pool/{pool_id}')
async def humble_pool_by_id(pool_id: int) -> Optional[humble.HumblePool]:
    return humble.get_pool_by_id(pool_id)


@app.get('/humble/pools')
async def humble_pools_by_assets(assetA: int, assetB: int) -> List[humble.HumblePool]:
    return humble.get_pools_by_assets(assetA, assetB)


@app.get('/humble/pools/all')
async def humble_pools_all() -> List[humble.HumblePool]:
    return humble.get_pools({})


# CROWDSALE

# def check_crowdsale_whitelist(contract_id: int, address: str) -> None:
#     contract = get_contract(contract_id)
#     if contract is None or contract.type != 'crowdsale':
#         raise HTTPException(status_code=404, detail="Contract not found")
#
#     whitelist = contract.metadata["whitelist"]
#     if address not in whitelist:
#         raise HTTPException(status_code=403, detail="Address not whitelisted")
#
#
# @app.put('/whitelist_confirm')
# async def whitelist_confirm(contract_id: int, address: str) -> bool:
#     check_crowdsale_whitelist(contract_id, address)
#     return await calljs("crowdsaleWhitelist", contractId=contract_id, addr=address)
#
#
# @app.get('/whitelist_check')
# async def whitelist_check(contract_id: int, address: str) -> bool:
#     check_crowdsale_whitelist(contract_id, address)
#     return True


# SWAP

@app.post('/swap/lottery')
async def record_swap_and_check_nft_lottery(swap: SwapInfo) -> Optional[NftPrize]:
    # TODO: check swap already recorded

    record_swap(swap)
    return lottery_for_swap(swap)


# LOTTERY

@app.post('/lottery/swap')
async def nft_lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    # TODO: check swap already recorded

    record_swap(swap)
    return lottery_for_swap(swap)


@app.post('/lottery/staking')
async def nft_lottery_for_staking(address: str, pool_id: int) -> Optional[NftPrize]:
    return await lottery_for_staking(pool_id, address)


@app.post('/lottery/new')
async def create_a_new_nft_lottery(lottery: NftLottery, password: str) -> None:
    check_password(password)
    if nft_lotteries.get_by_primary_key(lottery.name) is not None:
        raise HTTPException(status_code=409, detail='Lottery with such name already exists')
    nft_lotteries.create(lottery)


@app.post('/lottery/update')
async def update_nft_lottery(lottery: NftLottery, password: str) -> None:
    check_password(password)
    if nft_lotteries.get_by_primary_key(lottery.name) is None:
        raise HTTPException(status_code=404, detail=f'Lottery with name {lottery.name} not found')
    nft_lotteries.update(lottery)


@app.patch('/lottery/claim')
async def claim_prize_nft_for_swap(wallet: str) -> None:
    wins = lottery_draws.get_many({'wallet': wallet, 'claimed': False, 'prize': {'$ne': None}})
    if len(wins) == 0:
        raise HTTPException(status_code=404, detail=f'Lottery draws for {wallet} are not found')
    lottery_draw = wins[-1]

    try:
        send_nft(lottery_draw.wallet, lottery_draw.prize)
        lottery_draw.claimed = True
    except Exception as e:
        lottery_draw.send_error = str(e)

    lottery_draws.update(lottery_draw)


@app.get('/lotteries/')
async def get_lotteries(password: str) -> List[NftLottery]:
    check_password(password)
    return nft_lotteries.get_all()


@app.get('/lotteries/resend')
async def resend_prizes(password: str) -> List[NftLottery]:
    check_password(password)
    return send_all_prizes()


# Statistics

@app.get('/stats/tvl')
async def tvl() -> dict:
    return stats.get_tvl()


# Events

@app.on_event("startup")
async def startup_event():
    logger = logging.getLogger("uvicorn.access")
    console_formatter = ColourizedFormatter(
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        use_colors=True
    )
    logger.handlers[0].setFormatter(console_formatter)


def setup_logging():
    logging.basicConfig(
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=settings.logging_level
    )


setup_logging()

if __name__ == "__main__":
    argv = sys.argv[1:]

    if len(argv) > 0:
        command = argv[0]

        if command == 'airdrop':
            if len(argv) < 2:
                print('Provide airdrop id!')
                exit(1)
            airdrop_id = argv[1]
            snapshot.make_snapshot(airdrop_id)
            airdrop.run(airdrop_id)
            exit(0)

        print(f'Command "{command}" is unknown!')
        exit(1)

    if settings.migrate:
        print('MIGRATE = TRUE')
        migrate()

    with start_js_interop_server():
        with start_bg_tasks():
            uvicorn.run("app:app", host="0.0.0.0", port=settings.server_port, workers=settings.workers_num)
