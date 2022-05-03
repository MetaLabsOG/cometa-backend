import sys
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from airdrop import airdrop, snapshot
from airdrop.mint import change_meta_config
from api import market
from api.contract_manager import ContractInfo, get_contract, add_contract, get_contracts, remove_contract, \
    remove_contracts
from api.wallet_manager import AssetInfo, get_wallet_assets, TimedCost, get_wallet_total_cost, get_wallet_nfts, NftInfo

app = FastAPI(
    title="Cometa",
    version="0.1.3"
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


class AddContract(BaseModel):
    type: str
    id: int
    version: str
    description: Optional[str] = None


@app.post('/contract/add')
async def add_new_contract(contract: AddContract) -> dict:
    if get_contract(contract.id) is not None:
        raise HTTPException(status_code=409, detail="Contract already exists")

    added = add_contract(contract.type, contract.id, contract.version, contract.description)
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


# TINYMAN SWAP

@app.get('/asset_swap_cost')
async def asset_swap_cost(address: str, asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    client = init_test_tinyclient(address)
    res_tokens, price_per_token, _ = get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount)

    return {
        'res_tokens': res_tokens,
        'price_per_token': price_per_token
    }


@app.get('/swap_asset_transactions')
async def swap_asset_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    client = init_test_tinyclient(address)
    transactions, signed_transactions = get_swap_asset_transactions(client, asset1_id, asset2_id, asset1_amount)

    return {
        'transactions': transactions,
        'signed_transactions': signed_transactions
    }



if __name__ == "__main__":
    change_meta_config()
    exit(0)

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

    uvicorn.run(app, host="0.0.0.0", port=5001)
