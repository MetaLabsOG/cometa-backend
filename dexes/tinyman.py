import base64
from typing import Optional

from algosdk import account, encoding, mnemonic
from tinyman.assets import Asset
from tinyman.v1.client import TinymanTestnetClient, TinymanMainnetClient, TinymanClient

from blockchain.assets import ALGO_ASA_ID, USDC_ASA_ID
from blockchain.node import init_algod_client
from env import settings


ASSETS_PATH = 'https://asa-list.tinyman.org/assets.json'

private_key = mnemonic.to_private_key(settings.tinyman_mnemonic)
public_key = account.address_from_private_key(private_key)


def init_tinyman_client(address: Optional[str] = None) -> TinymanClient:
    algod_client = init_algod_client()
    if settings.is_mainnet():
        return TinymanMainnetClient(algod_client=algod_client, user_address=address)
    else:
        return TinymanTestnetClient(algod_client=algod_client, user_address=address)


def get_amount(micros: int, asset: Asset) -> float:
    decimals = 10 ** asset.decimals
    return micros / decimals


def get_micros(amount: float, asset: Asset) -> int:
    decimals = 10 ** asset.decimals
    return int(amount * decimals)


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


def check_optin(client: TinymanClient, asset_id: int, user_address: str):
    if not client.is_opted_in(user_address):
        print('Account not opted into app, opting in now..')
        transaction_group = client.prepare_app_optin_transactions(user_address)
        transaction_group.sign_with_private_key(public_key, private_key)
        result = client.submit(transaction_group, wait=True)

    if not client.asset_is_opted_in(asset_id, user_address):
        print(f'Account not opted into asset {asset_id}, opting in now..')
        transaction_group = client.prepare_asset_optin_transactions(asset_id, user_address)
        transaction_group.sign_with_private_key(public_key, private_key)
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
    # SWAP TOKEN1-TOKEN2
    res1, price_per_token2, _ = get_asset_swap_cost(client, token1_id, token2_id, token1_amount)

    # SWAP TOKEN1-ALGO-TOKEN2
    algos, price_per_algo, _ = get_asset_swap_cost(client, token1_id, ALGO_ASA_ID, token1_amount)
    res2, algo_per_token2, _ = get_asset_swap_cost(client, ALGO_ASA_ID, token2_id, algos)

    # SWAP DIFF IN USDC
    algos, price_per_algo, _ = get_asset_swap_cost(client, token2_id, ALGO_ASA_ID, res2 - res1)
    usdc_res, usdc_price, _ = get_asset_swap_cost(client, ALGO_ASA_ID, USDC_ASA_ID, algos)

    return res1, res2, usdc_res


def zap(client: TinymanClient, user_address: str, asset_id: int, microalgos: int) -> dict:
    ALGO = client.fetch_asset(ALGO_ASA_ID)
    asset2 = client.fetch_asset(asset_id)
    pool = client.fetch_pool(ALGO, asset2)

    check_optin(client, asset_id, user_address)

    half = microalgos // 2
    # TODO: set slippage
    quote = pool.fetch_fixed_input_swap_quote(ALGO(half), slippage=0.01)
    print(quote)
    print(f'price={quote.price}, amount_in={quote.amount_in}, amount_out={quote.amount_out}')

    transaction_group = pool.prepare_swap_transactions_from_quote(quote)
    transaction_group.sign_with_private_key(public_key, private_key)
    swap_tx = client.submit(transaction_group, wait=True)
    print(f'Swapped with: {swap_tx}')

    check_optin(client, pool.liquidity_asset.id, user_address)

    quote = pool.fetch_mint_quote(ALGO(half), slippage=0.01)
    print(quote)
    transaction_group = pool.prepare_mint_transactions_from_quote(quote)
    transaction_group.sign_with_private_key(public_key, private_key)
    add_liquidity_tx = client.submit(transaction_group, wait=True)
    print(f'Added liquidity with: {add_liquidity_tx}')

    info = pool.fetch_pool_position()
    share = info['share'] * 100
    print(f'Pool Tokens: {info[pool.liquidity_asset]}')
    print(f'Assets: {info[asset2]}, {info[ALGO]}')
    print(f'Share of pool: {share:.3f}%')

    return {'added_lp_tokens': info[pool.liquidity_asset]}
