from tinyman.v1.client import TinymanTestnetClient, TinymanMainnetClient
from algosdk import account, encoding
from algosdk.v2client import algod
import urllib.request, json
import base64


def init_test_tinyclient(address):
    algod_client = algod.AlgodClient('d5bjYQye8f6tfntYkkFZ32l9Yb1b9e098KyNZ69B',
                                     'https://testnet-algorand.api.purestake.io/ps2',
                                     headers={'User-Agent': 'py-algorand-sdk',
                                              'X-API-Key': 'd5bjYQye8f6tfntYkkFZ32l9Yb1b9e098KyNZ69B'})
    client = TinymanTestnetClient(algod_client=algod_client, user_address=address)

    return client


def init_main_tinyclient(address):
    algod_client = algod.AlgodClient('d5bjYQye8f6tfntYkkFZ32l9Yb1b9e098KyNZ69B',
                                     'https://mainnet-algorand.api.purestake.io/ps2',
                                     headers={'User-Agent': 'py-algorand-sdk',
                                              'X-API-Key': 'd5bjYQye8f6tfntYkkFZ32l9Yb1b9e098KyNZ69B'})
    client = TinymanMainnetClient(algod_client=algod_client, user_address=address)

    return client


def get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount):
    ASSETS_PATH = 'https://asa-list.tinyman.org/assets.json'
    asset_info = {}
    with urllib.request.urlopen(ASSETS_PATH) as url:
        asset_info = json.loads(url.read().decode())

    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)

    decimal1 = 10 ** asset_info[str(asset1_id)]['decimals']
    decimal2 = 10 ** asset_info[str(asset2_id)]['decimals']

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
