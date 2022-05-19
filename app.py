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
from api.js_interop import calljs

from dexes.tinyman import get_swap_asset_transactions, init_tinyman_client, get_pool_info, zap, \
    get_best_swap, get_optin_transactions, get_fee_transaction, encode_transactions
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

class DeployContract(BaseModel):
    type: str
    settings: dict
    metadata: Optional[dict] = None
    description: Optional[str] = None

@app.post('/contract/deploy')
async def deploy_contract(password: str, parameters: DeployContract) -> dict:
    check_password(password)
    version = calljs("contractVersion", contractType=parameters.type)
    contract_id = calljs("deployContract", contractType=parameters.type, contractSettings=parameters.settings)
    added = add_contract(parameters.type, contract_id, version, parameters.description, parameters.metadata)
    return {'internal_id': added}

@app.get('/contract_version')
async def get_contract_version(type: str) -> dict:
    version = calljs("contractVersion", contractType=type)
    return {'version': version}

# TINYMAN SWAP

@app.get('/best_swap')
async def best_swap(asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    # TODO
    client = init_tinyman_client(settings.algod_address)
    return get_best_swap(client, asset1_id, asset2_id, asset1_amount)


@app.get('/routing_transactions')
async def routing_transactions(address: str, asset1_id: int, asset2_id: int, asset1_amount: float) -> dict:
    TXNS_FIELD = 'txns'
    SIGNED_TXNS_FIELD = 'signed_txns'

    client = init_tinyman_client(address)
    try:
        transactions = []
        tx_id = ''
        optin_transactions = get_optin_transactions(client, asset2_id)
        if len(optin_transactions) > 0:
            transactions.append({
                TXNS_FIELD: optin_transactions,
                SIGNED_TXNS_FIELD: ['' for _ in range(len(optin_transactions))]
            })

        best_tokens_swap = get_best_swap(client, asset1_id, asset2_id, asset1_amount)
        for num, token in enumerate(best_tokens_swap['best_path'][:-1]):
            cur_asset_id = token['asset_id']
            cur_asset_amount = token['amount']
            next_asset_id = best_tokens_swap['best_path'][num + 1]['asset_id']

            # if we swap through algo then pay commission
            # if cur_asset_id == 0 and len(best_tokens_swap['best_path']) > 2:
            #     algo_amount = cur_asset_amount
            #     TODO: fix calculation (Y - X) * 10% * A / Y
            #     fee_amount = algo_amount * 0.01
            #     cur_asset_amount -= fee_amount
            #     fee_txn = get_fee_transaction(client, address, fee_amount)
            #     encoded_fee_txn = encode_transactions([fee_txn])
            #     transactions.append({
            #         TXNS_FIELD: encoded_fee_txn,
            #         SIGNED_TXNS_FIELD: [[]]
            #     })

            swap_transactions, swap_signed_transactions, tx_id = get_swap_asset_transactions(
                client, cur_asset_id, next_asset_id, cur_asset_amount)
            transactions.append({
                TXNS_FIELD: swap_transactions,
                SIGNED_TXNS_FIELD: swap_signed_transactions
            })

        return {
            'transactions': transactions,
            'tx_id': tx_id
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get('/pool')
async def pool(asset1_id: int, asset2_id: int) -> dict:
    client = init_tinyman_client()
    return get_pool_info(client, asset1_id, asset2_id)


@app.get('/zap')
async def prepare_zap(user_address: str, asset_id: int, microalgos: int) -> dict:
    client = init_tinyman_client()
    return zap(client, user_address, asset_id, microalgos)

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
    return calljs("crowdsaleWhitelist", contractId=contract_id, addr=address)

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

    uvicorn.run(app, host="0.0.0.0", port=settings.server_port)
