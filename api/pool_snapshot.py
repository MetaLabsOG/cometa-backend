import json
from collections import defaultdict
from typing import Optional

from algosdk.v2client import indexer

from blockchain.node import get_current_round
from env import settings

indexer_client = indexer.IndexerClient(indexer_token='', indexer_address=settings.algo_indexer_address)

ASSET_TRANSFER_TX = 'asset-transfer-transaction'
APPLICATION_CALL_TX = 'application-transaction'
PAYMENT_TX = 'payment-transaction'


def get_pool_wallet(pool_id: int) -> Optional[str]:
    data = indexer_client.application_logs(application_id=pool_id, limit=10)

    print(f'\n\n\n\n\n\nlog = {json.dumps(data, indent=2)}\n\n\n\n\n\n')

    # url = f'{BASE_URL}/v2/applications/{pool_id}/logs?limit=10'
    # data = requests.get(url).json()
    log_data = data.get('log-data')
    if log_data is None or len(log_data) == 0:
        return None

    print(f'\n\n\n\n\n\nlog = {json.dumps(log_data, indent=2)}\n\n\n\n\n\n')

    # I could use SDK here, but I'm lazy
    txid = log_data[0]['txid']
    # url = f'{BASE_URL}/v2/transactions/{txid}'
    # data = requests.get(url).json()
    data = indexer_client.transaction(txid=txid)

    print(f'\n\n\n\n\n\nlog = {json.dumps(data, indent=2)}\n\n\n\n\n\n')

    transaction = data.get('transaction')

    print(f'\n\n\n\n\n\ntx = {json.dumps(transaction, indent=2)}\n\n\n\n\n\n')

    if transaction is None:
        return None

    return transaction['inner-txns'][0]['sender']


def get_pool_snapshot(pool_id: int, max_round: Optional[int] = None, watch_address: Optional[str] = None):
    pool_wallet = get_pool_wallet(pool_id)
    if pool_wallet is None:
        pool_wallet = get_pool_wallet(pool_id)
    if pool_wallet is None:
        return {'error': 'Pool not found, bro.'}
    print(f'Pool wallet: {pool_wallet}')

    if max_round is None:
        max_round = get_current_round()

    next_token = None
    all_txns = []
    balances = defaultdict(lambda: 0)

    if watch_address is not None:
        print(f'Watching address {watch_address}')

    while True:
        data = indexer_client.search_transactions_by_address(address=pool_wallet,
                                                             next_page=next_token)
        txns = data['transactions']
        print(f'New txns, cnt = {len(txns)}')

        for tx in txns:
            if ASSET_TRANSFER_TX in tx:
                if max_round is not None and tx['confirmed-round'] > max_round:
                    continue

                sender = tx['sender']
                amount = tx[ASSET_TRANSFER_TX]['amount']
                if sender == watch_address:
                    print(f'{balances[sender]} + {amount} = {balances[sender] + amount}')
                balances[sender] += amount
            elif APPLICATION_CALL_TX in tx:
                inner_txns = tx['inner-txns']
                is_claim = False
                for inner_tx in inner_txns:
                    if PAYMENT_TX in inner_tx:
                        is_claim = True
                if is_claim:
                    continue
                for inner_tx in inner_txns:
                    if ASSET_TRANSFER_TX in inner_tx:
                        if inner_tx['confirmed-round'] > max_round:
                            continue

                        receiver = inner_tx[ASSET_TRANSFER_TX]['receiver']
                        amount = inner_tx[ASSET_TRANSFER_TX]['amount']
                        if receiver == watch_address:
                            print(f'{balances[receiver]} - {amount} = {balances[receiver] - amount}')
                        balances[receiver] -= amount

        print(f'{len(txns)} txns processed!')
        print(f'Currently {len(balances)} balances')
        print()

        all_txns.extend(txns)
        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    res_filename = f'pool_{pool_id}_round_{max_round}.json'
    with open(res_filename, 'w') as write_file:
        json.dump(balances, write_file, indent=4, sort_keys=True)

    print(f'{len(all_txns)} processed!')
    print(f'{len(balances)} wallets are written to "{res_filename}"!')

    total_microtokens = 0
    for k, v in balances.items():
        total_microtokens += v

    print(f'In total {total_microtokens} microtokens')

    return balances


# if __name__ == '__main__':
#     snapshot = get_pool_snapshot(1097496346)
#     print(json.dumps(snapshot, indent=4, sort_keys=True))
