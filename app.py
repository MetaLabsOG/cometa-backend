import secrets
import sys
from typing import List, Optional, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware


from airdrop import airdrop, snapshot
from api import nft_market
from api.contract_manager import ContractInfo, get_contract, add_contract, get_contracts, remove_contract, \
    remove_contracts, update_contract
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, \
    NftInfo, get_wallet_assets2

from dexes.tinyman import init_tinyman_client, get_pool_info, get_swap_data, get_zap_transactions, \
    get_swap_transactions, get_zap_data
from env import settings

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


# TINYMAN SWAP

@app.get('/swap_data')
async def swap_data(asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    # TODO
    client = init_tinyman_client(settings.algod_address)
    return get_swap_data(client, asset1_id, asset2_id, asset1_amount)


@app.get('/swap_transactions')
async def swap_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    client = init_tinyman_client(address)
    try:
        result = get_swap_transactions(client, asset1_id, asset2_id, asset1_amount)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get('/pool')
async def pool(asset1_id: int, asset2_id: int) -> dict:
    client = init_tinyman_client()
    return get_pool_info(client, asset1_id, asset2_id)


@app.get('/zap_data')
async def zap_data(asset1_id: int, asset2_id: int, asset1_amount: float, swap_half: bool) -> dict:
    client = init_tinyman_client(settings.algod_address)
    try:
        result = get_zap_data(client, asset1_id, asset2_id, asset1_amount, swap_half)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get('/zap_transactions')
async def zap_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float, swap_half: bool) -> dict:
    client = init_tinyman_client(address)
    try:
        result = get_zap_transactions(client, asset1_id, asset2_id, asset1_amount, swap_half)
        return result
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


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

    uvicorn.run(app, host="0.0.0.0", port=settings.server_port)
