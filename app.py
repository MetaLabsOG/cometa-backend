import time
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware

from api import market
from api.contract_manager import ContractInfo, get_contract, add_contract, get_contracts, remove_contract, \
    remove_contracts
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, NftInfo

# TODO: fixrouting to /api
app = FastAPI(
    title="Cometa",
    version="0.1.1"
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


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return market.get_floor_price(asset_id)


@app.get('/wallet_assets/{address}')
async def wallet_assets(address: str) -> List[AssetInfo]:
    return get_wallet_assets(address)


@app.get('/total_cost/{address}')
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> List[TimedCost]:
    return get_wallet_total_cost(address, weeks_count)


@app.get('/wallet_nfts/{address}')
async def wallet_nfts(address: str) -> List[NftInfo]:
    return get_wallet_nfts(address)


@app.post('/contract/add')
async def add_new_contract(contract: ContractInfo) -> dict:
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    # Sets db adding time as deployment time if not provided explicitly.
    if contract.deployed_timestamp is None:
        contract.deployed_timestamp = time.time()
    added = add_contract(contract)
    return {'internal_id': added}


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
async def remove_contract_by_id(contract_id: int) -> dict:
    cnt = remove_contract(contract_id=contract_id)
    return {'deleted_count': cnt}


@app.delete('/contracts')
async def remove_contracts_by_type(type: str) -> dict:
    cnt = remove_contracts(type=type)
    return {'deleted_count': cnt}

# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=5001)
