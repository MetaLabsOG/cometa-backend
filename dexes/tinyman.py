from typing import Optional

from algosdk import account, encoding, mnemonic
from algosdk.v2client.algod import AlgodClient
from tinyman.assets import Asset
from tinyman.v1.client import TinymanTestnetClient, TinymanMainnetClient, TinymanClient
from tinyman.utils import TransactionGroup
from algosdk.future.transaction import ApplicationOptInTxn, AssetOptInTxn, PaymentTxn

from blockchain.assets import ALGO_ASA_ID, USDC_ASA_ID
from blockchain.node import init_algod_client
from env import settings


private_key = mnemonic.to_private_key(settings.tinyman_mnemonic)
public_key = account.address_from_private_key(private_key)


def tinyman_from_algod(algod_client: AlgodClient, address: Optional[str] = public_key) -> TinymanClient:
    if settings.is_mainnet():
        return TinymanMainnetClient(algod_client=algod_client, user_address=address)
    else:
        return TinymanTestnetClient(algod_client=algod_client, user_address=address)


def init_tinyman_client(address: Optional[str] = public_key) -> TinymanClient:
    algod_client = init_algod_client()
    return tinyman_from_algod(algod_client, address)


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


def get_price_algo(client: TinymanClient, asset_id: int) -> float:
    ALGO = client.fetch_asset(ALGO_ASA_ID)
    asset = client.fetch_asset(asset_id)
    pool = client.fetch_pool(asset, ALGO)
    print(f'asset1={pool.asset1_price}, asset2={pool.asset2_price}')
    return pool.asset1_price


def get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)

    quote = pool.fetch_fixed_input_swap_quote(asset1(get_micros(asset1_amount, asset1)), slippage=0.01)

    return pool, quote


def get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool, quote = get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount)

    decimal1 = 10 ** asset1.decimals
    decimal2 = 10 ** asset2.decimals

    price_per_token = quote.price * decimal1 / decimal2
    res_tokens = price_per_token * asset1_amount

    return float(res_tokens), float(price_per_token)


def get_optin_transactions(client, asset_id):
    optin_txns = []
    suggested_params = client.algod.suggested_params()
    if not client.is_opted_in():
        txn = ApplicationOptInTxn(
            sender=client.user_address,
            sp=suggested_params,
            index=client.validator_app_id,
        )
        optin_txns.append(txn)

    if asset_id > 0 and not client.asset_is_opted_in(asset_id):
        txn = AssetOptInTxn(
            sender=client.user_address,
            sp=suggested_params,
            index=asset_id,
        )
        optin_txns.append(txn)

    transaction_group = TransactionGroup(optin_txns)

    return encode_transactions(transaction_group.transactions)


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
            encode_trans.append(txn)
        else:
            encode_trans.append([])
    return encode_trans


def get_swap_asset_transactions(client, asset1_id, asset2_id, asset1_amount):
    pool, quote = get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount)
    transaction_group = pool.prepare_swap_transactions_from_quote(quote)

    tx_id = transaction_group.transactions[0].get_txid()

    encoded_transactions = encode_transactions(transaction_group.transactions)
    encoded_signed_transactions = encode_transactions(transaction_group.signed_transactions)

    return encoded_transactions, encoded_signed_transactions, tx_id


def get_fee_transaction(client, address, fee):
    receiver = 'METAZZXDNBTZSI5PQORZD3Z7GMDXGJBZ3ZZXWS43KARTPGV4ZDOIWQPIF4'

    suggested_params = client.algod.suggested_params()
    fee = int(fee * 10 ** 6)

    return PaymentTxn(
        sender=address,
        sp=suggested_params,
        receiver=receiver,
        amt=fee,
        note='fee',
    )


def get_best_swap(client, token1_id, token2_id, token1_amount):
    asset1 = client.fetch_asset(token1_id)
    asset2 = client.fetch_asset(token2_id)

    best_tokens, best_path = 0, []
    best_path.append({
        'asset_id': token1_id,
        'unit_name': asset1.unit_name,
        'amount': token1_amount
    })

    # SWAP TOKEN1-TOKEN2
    try:
        direct_tokens, _ = get_asset_swap_cost(client, token1_id, token2_id, token1_amount)
        best_tokens = direct_tokens
    except:
        direct_tokens = 0

    # SWAP TOKEN1-ALGO-TOKEN2
    try:
        algos, _ = get_asset_swap_cost(client, token1_id, ALGO_ASA_ID, token1_amount)
        # transactions commissions
        algos -= 0.002 * 2
        res, _ = get_asset_swap_cost(client, ALGO_ASA_ID, token2_id, algos)
        if res > best_tokens:
            best_tokens = res
            best_path.append({
                'asset_id': ALGO_ASA_ID,
                'unit_name': 'ALGO',
                'amount': algos
            })
    except:
        pass

    best_path.append({
        'asset_id': token2_id,
        'unit_name': asset2.unit_name,
        'amount': best_tokens
    })

    # SWAP DIFF IN USDC
    try:
        algos_diff, _ = get_asset_swap_cost(client, token2_id, ALGO_ASA_ID, max(0, best_tokens - direct_tokens))
        usdc_diff, _ = get_asset_swap_cost(client, ALGO_ASA_ID, USDC_ASA_ID, algos_diff)
    except:
        usdc_diff = 0

    return {
        'best_swap': best_tokens,
        'best_path': best_path,
        'direct_swap': direct_tokens,
        'usdc_diff': usdc_diff,
    }


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

