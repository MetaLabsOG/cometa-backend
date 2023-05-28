import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional

from algosdk import account, encoding, mnemonic
from algosdk.future.transaction import ApplicationOptInTxn, AssetOptInTxn, PaymentTxn
from algosdk.v2client.algod import AlgodClient
from cachetools import TTLCache, cached
from tinyman.assets import Asset
from tinyman.utils import TransactionGroup
from tinyman.v2.client import TinymanV2MainnetClient, TinymanV2TestnetClient, TinymanV2Client

from blockchain.assets import ALGO_ASA_ID, USDC_ASA_ID
from blockchain.node import init_algod_client
from env import settings

ASSETS_PATH = 'https://asa-list.tinyman.org/assets.json'

TXNS_FIELD = 'txns'
SIGNED_TXNS_FIELD = 'signed_txns'
TX_ID_FIELD = 'tx_id'


private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)

logger = logging.getLogger(__name__)


def tinyman_from_algod(algod_client: AlgodClient, address: Optional[str] = public_key) -> TinymanV2Client:
    if settings.is_mainnet():
        return TinymanV2MainnetClient(algod_client=algod_client, user_address=address)
    else:
        return TinymanV2TestnetClient(algod_client=algod_client, user_address=address)


def init_tinyman_client(address: Optional[str] = public_key) -> TinymanV2Client:
    algod_client = init_algod_client()
    return tinyman_from_algod(algod_client, address)


def get_amount(micros: int, asset: Asset) -> float:
    decimals = 10 ** asset.decimals
    return micros / decimals


def get_micros(amount: float, asset: Asset) -> int:
    decimals = 10 ** asset.decimals
    return int(amount * decimals)


@dataclass
class PoolInfo:
    name: str
    asset1_reserve: float
    asset2_reserve: float
    total_lp_tokens: float


def get_pool_info(client: TinymanV2Client, asset1_id: int, asset2_id: int) -> PoolInfo:
    # class are cached inside TinymanClient
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)

    pool = client.fetch_pool(asset1, asset2)

    logger.debug(f'Found pool for assets {asset1_id} and {asset2_id}: {pool}')

    if pool.asset_1_reserves is None or pool.asset_2_reserves is None or pool.issued_liquidity is None:
        raise ValueError(f'For assests {asset1_id} and {asset2_id} pool is empty:\n{pool}')

    asset_1_reserve = get_amount(pool.asset_1_reserves, pool.asset1)
    asset_2_reserve = get_amount(pool.asset_2_reserves, pool.asset2)
    total_lp_tokens = get_amount(pool.issued_liquidity, pool.liquidity_asset)

    # Because Tinyman SDK swap them inside Pool
    if asset1_id < asset2_id:
        tmp = asset_1_reserve
        asset_1_reserve = asset_2_reserve
        asset_2_reserve = tmp

    return PoolInfo(pool.liquidity_asset.name, asset_1_reserve, asset_2_reserve, total_lp_tokens)


def get_price(client: TinymanV2Client, asset_id: int) -> float:
    if asset_id == ALGO_ASA_ID:
        return 1
    ALGO = client.fetch_asset(ALGO_ASA_ID)
    asset = client.fetch_asset(asset_id)
    pool = client.fetch_pool(asset, ALGO)
    return pool.asset1_price


def get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount, slippage: float):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)

    quote = pool.fetch_fixed_input_swap_quote(asset1(get_micros(asset1_amount, asset1)), slippage=slippage)

    return pool, quote


def get_asset_swap_cost(client, asset1_id, asset2_id, asset1_amount, slippage: float):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool, quote = get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount, slippage)

    decimal1 = 10 ** asset1.decimals
    decimal2 = 10 ** asset2.decimals

    price_per_token = quote.price * decimal1 / decimal2
    res_tokens = price_per_token * asset1_amount

    return float(res_tokens)


def get_optin_transactions(client, asset_id, optin_client=True):
    optin_txns = []
    suggested_params = client.algod.suggested_params()
    if optin_client and not client.is_opted_in():
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
    tx_id = ''
    if len(transaction_group.transactions) > 0:
        tx_id = transaction_group.transactions[0].get_txid()

    return encode_transactions(transaction_group.transactions), tx_id


def check_optin(client: TinymanV2Client, asset_id: int, user_address: str):
    if not client.is_opted_in(user_address):
        print('Account not opted into app, opting in now..')
        transaction_group = client.prepare_asset_optin_transactions(asset_id=asset_id, user_address=user_address)
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


def get_swap_asset_transactions(client, asset1_id, asset2_id, asset1_amount, slippage: float):
    pool, quote = get_asset_swap_pool(client, asset1_id, asset2_id, asset1_amount, slippage)
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


def get_swap_data(client, token1_id, token2_id, token1_amount, slippage: float):
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
        direct_tokens = get_asset_swap_cost(client, token1_id, token2_id, token1_amount, slippage)
        best_tokens = direct_tokens
    except:
        direct_tokens = 0

    # SWAP TOKEN1-ALGO-TOKEN2
    try:
        algos = get_asset_swap_cost(client, token1_id, ALGO_ASA_ID, token1_amount, slippage)
        # transactions commissions
        algos -= 0.002 * 2
        res = get_asset_swap_cost(client, ALGO_ASA_ID, token2_id, algos, slippage)
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
        algos_diff = get_asset_swap_cost(client, token2_id, ALGO_ASA_ID, max(0, best_tokens - direct_tokens), slippage)
        usdc_diff = get_asset_swap_cost(client, ALGO_ASA_ID, USDC_ASA_ID, algos_diff, slippage)
    except:
        usdc_diff = 0

    return {
        'best_swap': best_tokens,
        'best_path': best_path,
        'direct_swap': direct_tokens,
        'usdc_diff': usdc_diff,
    }


def zap(client: TinymanV2Client, user_address: str, asset_id: int, microalgos: int) -> dict:
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


def get_swap_transactions(client, asset1_id, asset2_id, asset1_amount, slippage: float):
    transactions = []
    tx_id = ''
    optin_transactions, tx_id = get_optin_transactions(client, asset2_id)
    if len(optin_transactions) > 0:
        transactions.append({
            TXNS_FIELD: optin_transactions,
            SIGNED_TXNS_FIELD: ['' for _ in range(len(optin_transactions))],
            TX_ID_FIELD: tx_id
        })

    best_tokens_swap = get_swap_data(client, asset1_id, asset2_id, asset1_amount, slippage)
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
            client, cur_asset_id, next_asset_id, cur_asset_amount, slippage)
        transactions.append({
            TXNS_FIELD: swap_transactions,
            SIGNED_TXNS_FIELD: swap_signed_transactions,
            TX_ID_FIELD: tx_id
        })

    return {
        'transactions': transactions,
        'tx_id': tx_id
    }


def get_zap_pool(client, asset1_id, asset2_id, asset1_amount, slippage: float):
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)
    quote = pool.fetch_mint_quote(asset1(get_micros(asset1_amount, asset1)), slippage=slippage)

    return asset1, asset2, pool, quote


def get_zap_data(client, asset1_id, asset2_id, asset1_amount, swap_half, slippage: float):
    asset1_amount = asset1_amount / 2 if swap_half else asset1_amount
    asset1, asset2, pool, quote = get_zap_pool(client, asset1_id, asset2_id, asset1_amount, slippage)
    pool_lp_id = pool.liquidity_asset.id

    asset2_amount = get_amount(quote.amounts_in[asset2].amount, asset2)
    lp_amount = get_amount(quote.liquidity_asset_amount.amount, quote.liquidity_asset_amount.asset)
    print(asset2_amount, lp_amount)

    return {
        'asset1_amount': asset1_amount,
        'asset2_amount': asset2_amount,
        'lp_amount': lp_amount,
        'pool_lp_id': pool_lp_id
    }


def get_zap_transactions(client, asset1_id, asset2_id, asset1_amount, swap_half, slippage: float):
    asset1_amount = asset1_amount / 2 if swap_half else asset1_amount
    asset2_amount = get_swap_data(client, asset1_id, asset2_id, asset1_amount, slippage)['best_swap']
    # TODO: easy fix
    asset2_amount *= (1 - slippage - 0.01)
    asset1, asset2, pool, quote = get_zap_pool(client, asset2_id, asset1_id, asset2_amount, slippage)
    pool_lp_id = pool.liquidity_asset.id

    transactions = []

    if swap_half:
        swap_transactions = get_swap_transactions(client, asset1_id, asset2_id, asset1_amount, slippage)
        transactions = swap_transactions['transactions']

    optin_transactions, tx_id = get_optin_transactions(client, pool_lp_id, False)
    if len(optin_transactions) > 0:
        transactions.append({
            TXNS_FIELD: optin_transactions,
            SIGNED_TXNS_FIELD: ['' for _ in range(len(optin_transactions))],
            TX_ID_FIELD: tx_id
        })

    transaction_group = pool.prepare_mint_transactions_from_quote(quote)

    tx_id = transaction_group.transactions[0].get_txid()
    encoded_transactions = encode_transactions(transaction_group.transactions)
    encoded_signed_transactions = encode_transactions(transaction_group.signed_transactions)

    transactions.append({
        TXNS_FIELD: encoded_transactions,
        SIGNED_TXNS_FIELD: encoded_signed_transactions,
        TX_ID_FIELD: tx_id
    })

    return {
        'transactions': transactions,
        'tx_id': tx_id
    }


# TODO: move asset infos to DB
@cached(cache=TTLCache(maxsize=1, ttl=settings.asset_prices_ttl))
def get_all_assets():
    with urllib.request.urlopen(ASSETS_PATH) as url:
        return json.loads(url.read().decode())


def get_asset_info(asset_id: int) -> Optional[dict]:
    return get_all_assets().get(str(asset_id))

