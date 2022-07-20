import secrets
import sys
from typing import List, Optional, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from algosdk import account, mnemonic

from airdrop import airdrop, snapshot
from api import nft_market
from api.contract_manager import ContractInfo, get_contract, add_contract, get_contracts, remove_contract, \
    remove_contracts, update_contract
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, \
    NftInfo, get_wallet_assets2
from api.util import parse_bignum
from api.js_interop import calljs, start_js_interop_server

from dexes.tinyman import init_tinyman_client, get_pool_info, get_swap_data, get_zap_transactions, \
    get_swap_transactions, get_zap_data
from env import settings
from background import start_bg_tasks

app = FastAPI(
    title="Cometa",
    version="0.1.5"
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
        'algo_network': settings.algo_network
    }


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return nft_market.get_floor_price(asset_id)


@app.get('/wallet_assets/{address}')
async def wallet_assets(address: str) -> List[AssetInfo]:
    return get_wallet_assets(address)


@app.get('/wallet_assets2/{address}')
async def wallet_assets(address: str) -> Dict[str, AssetInfo]:
    return get_wallet_assets2(address)


@app.get('/total_cost/{address}')
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> List[TimedCost]:
    return get_wallet_total_cost(address, weeks_count)


@app.get('/wallet_nfts/{address}')
async def wallet_nfts(address: str) -> List[NftInfo]:
    return get_wallet_nfts(address)


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
async def register_contract(contract: AddContract) -> dict:
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    global_views = await calljs("fetchContractsGlobalViews", contractType=contract.type, ids=[contract.id])
    if str(contract.id) not in global_views:
        raise HTTPException(status_code=409, detail="Contract with given ID is not present in the network or does not match the given type")

    view = global_views[str(contract.id)]

    # Check that the contract's parameters are correct (beneficiary and creation fee are as we need them)    
    # Assuming that beneficiary address is our account stored in ALGO_MNEMONIC variable
    if contract.type == 'farm':
        target_beneficiary = account.address_from_private_key(mnemonic.to_private_key(settings.algo_mnemonic))
        target_creation_fee = 0  # make farm creation free for now. TODO: should be set up in some ENV variable which is 
                                 # tied to the same variable on the frontend?

        if view['initial']['beneficiary'] != target_beneficiary:
            raise HTTPException(status_code=403, detail=f"Farm's beneficiary address is invaild (expected {target_beneficiary}")

        if parse_bignum(view['initial']['creationFee']) != target_creation_fee:
            raise HTTPException(status_code=403, detail=f"Farm's creation fee is invalid (expected {target_creation_fee}")

    # Cache the contract's state right away so that user sees that it is displayed correctly right after
    # the contract is created even without connected wallet.
    cache_metadata = {"cache": view}
    metadata = cache_metadata if contract.metadata is None else {**contract.metadata, **cache_metadata}
    added = add_contract(contract.type, contract.id, contract.version, contract.description, metadata)

    # I don't think that returning internal id to the users is anyhow useful, also probably discloses unnecessary info?
    return {'added': contract.id}

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


@app.get('/contracts')
async def get_contracts_by_type(type: str) -> List[ContractInfo]:
    return get_contracts(type)


@app.delete('/contract/{contract_id}')
async def remove_contract_by_id(contract_id: int, password: str) -> dict:
    check_password(password)
    cnt = remove_contract(contract_id=contract_id)
    return {'deleted_count': cnt}


@app.delete('/contracts')
async def remove_contracts_by_type(type: str, password: str) -> dict:
    check_password(password)
    cnt = remove_contracts(type=type)
    return {'deleted_count': cnt}


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


@app.get('/contract_version')
async def get_contract_version(type: str) -> dict:
    version = await calljs("contractVersion", contractType=type)
    return {'version': version}


# TINYMAN SWAP


@app.get('/swap_data')
async def swap_data(asset1_id: int, asset2_id: int, asset1_amount: float, slippage: float = 0.01) -> dict:
    # TODO
    client = init_tinyman_client(settings.algod_address)
    return get_swap_data(client, asset1_id, asset2_id, asset1_amount, slippage)


@app.get('/swap_transactions')
async def swap_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float,
                            slippage: float = 0.01) -> dict:
    client = init_tinyman_client(address)
    try:
        result = get_swap_transactions(client, asset1_id, asset2_id, asset1_amount, slippage)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get('/pool')
async def pool(asset1_id: int, asset2_id: int) -> dict:
    client = init_tinyman_client()
    return get_pool_info(client, asset1_id, asset2_id)


@app.get('/zap_data')
async def zap_data(asset1_id: int, asset2_id: int, asset1_amount: float, swap_half: bool,
                   slippage: float = 0.01) -> dict:
    client = init_tinyman_client(settings.algod_address)
    try:
        result = get_zap_data(client, asset1_id, asset2_id, asset1_amount, swap_half, slippage)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get('/zap_transactions')
async def zap_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float, swap_half: bool,
                           slippage: float = 0.01) -> dict:
    client = init_tinyman_client(address)
    try:
        result = get_zap_transactions(client, asset1_id, asset2_id, asset1_amount, swap_half, slippage)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# CROWDSALE

def check_crowdsale_whitelist(contract_id: int, address: str) -> None:
    contract = get_contract(contract_id)
    if contract is None or contract.type != 'crowdsale':
        raise HTTPException(status_code=404, detail="Contract not found")

    whitelist = contract.metadata["whitelist"]
    if address not in whitelist:
        raise HTTPException(status_code=403, detail="Address not whitelisted")


@app.put('/whitelist_confirm')
async def whitelist_confirm(contract_id: int, address: str) -> bool:
    check_crowdsale_whitelist(contract_id, address)
    return await calljs("crowdsaleWhitelist", contractId=contract_id, addr=address)


@app.get('/whitelist_check')
async def whitelist_check(contract_id: int, address: str) -> bool:
    check_crowdsale_whitelist(contract_id, address)
    return True


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

    with start_js_interop_server():
        with start_bg_tasks():
            uvicorn.run("app:app", host="0.0.0.0", port=settings.server_port)
