import base64
import json
import urllib.request
from typing import Optional

from algosdk import account, encoding
from tinyman.assets import Asset
from tinyman.v1.client import TinymanTestnetClient, TinymanMainnetClient, TinymanClient

from blockchain.node import init_algod_client
from env import settings


def init_tinyman_client(address: Optional[str] = None) -> TinymanClient:
    algod_client = init_algod_client()
    if settings.is_mainnet():
        return TinymanMainnetClient(algod_client=algod_client, user_address=address)
    else:
        return TinymanTestnetClient(algod_client=algod_client, user_address=address)


# TODO: use in other methods
def get_amount(micros: int, asset: Asset) -> float:
    decimals = 10 ** asset.decimals
    return micros / decimals


def get_pool_info(client: TinymanClient, asset1_id: int, asset2_id: int) -> dict:
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)

    pool = client.fetch_pool(asset1, asset2)

    asset1_reserve = get_amount(pool.asset1_reserves, pool.asset1)
    asset2_reserve = get_amount(pool.asset2_reserves, pool.asset2)
    total_lp_tokens = get_amount(pool.issued_liquidity, pool.liquidity_asset)

    # Because Tinyman SDK swap them inside Pool
    if asset1_id < asset2_id:
        tmp = asset1_reserve
        asset1_reserve = asset2_reserve
        asset2_reserve = tmp

    return {
        'name': pool.liquidity_asset.name,
        'asset1_reserve': asset1_reserve,
        'asset2_reserve': asset2_reserve,
        'total_lp_tokens': total_lp_tokens
    }


def get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)

    decimal1 = 10 ** asset1.decimals
    decimal2 = 10 ** asset2.decimals

    quote = pool.fetch_fixed_input_swap_quote(asset1(asset1_amount * decimal1), slippage=0.01)
    price_per_token = quote.price * decimal1 / decimal2
    res_tokens = price_per_token * asset1_amount

    return float(res_tokens), float(price_per_token), quote


# TODO
def check_optin(client, asset_id):
    if not client.is_opted_in():
        print('Account not opted into app, opting in now..')
        transaction_group = client.prepare_app_optin_transactions()
        transaction_group.sign_with_private_key(account['address'], account['private_key'])
        result = client.submit(transaction_group, wait=True)

    if not client.asset_is_opted_in(asset_id):
        print('Account not opted into asset, opting in now..')
        transaction_group = client.prepare_asset_optin_transactions(asset_id)
        transaction_group.sign_with_private_key(account['address'], account['private_key'])
        result = client.submit(transaction_group, wait=True)


def encode_transactions(transactions):
    encode_trans = []
    for txn in transactions:
        if txn:
            txn = encoding.msgpack_encode(txn)
            txn = base64.b64decode(txn)
            encode_trans.append(list(txn))
        else:
            encode_trans.append([])
    return encode_trans


def get_swap_asset_transactions(client, asset1_id, asset2_id, asset1_amount):
    _, _, quote = get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount)
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)
    transaction_group = pool.prepare_swap_transactions_from_quote(quote)

    encoded_transactions = encode_transactions(transaction_group.transactions)
    encoded_signed_transactions = encode_transactions(transaction_group.signed_transactions)

    return encoded_transactions, encoded_signed_transactions


def get_swap_diff(client, token1_id, token2_id, token1_amount):
    ALGO_ASA_ID = 0
    USDC_ASA_ID = 123
    # SWAP TOKEN1-TOKEN2
    res1, price_per_token2, _ = get_asset_swap_cost(client, token1_id, token2_id, token1_amount)

    # SWAP TOKEN1-ALGO-TOKEN2
    algos, price_per_algo, _ = get_asset_swap_cost(client, token1_id, ALGO_ASA_ID, token1_amount)
    res2, algo_per_token2, _ = get_asset_swap_cost(client, ALGO_ASA_ID, token2_id, algos)

    # SWAP DIFF IN USDC
    algos, price_per_algo, _ = get_asset_swap_cost(client, token2_id, ALGO_ASA_ID, res2 - res1)
    usdc_res, usdc_price, _ = get_asset_swap_cost(client, ALGO_ASA_ID, USDC_ASA_ID, algos)

    return res1, res2, usdc_res
