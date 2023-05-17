import json
from collections import defaultdict

from algosdk.v2client import indexer

indexer_client = indexer.IndexerClient(indexer_token='', indexer_address='https://algoindexer.algoexplorerapi.io/')

POOL_ADDRESS = 'CFSN7O7IVXFI5TVEQUCBKIFLWWMYUA4D32EHGALFZ7HM25JA5LIGQJIL7Q'
ASSET_TRANSFER_TX = 'asset-transfer-transaction'
APPLICATION_CALL_TX = 'application-transaction'
PAYMENT_TX = 'payment-transaction'

WATCH_ADDRESS = '5P3FC5YZ4ZC2JN3VBYYQ62CYMTNKXMZLJQ6LMLPKPWZD2NVJQLECJWVK5E'

MAX_ROUND = 29858365  # last


if __name__ == '__main__':
    next_token = None
    all_txns = []
    balances = defaultdict(lambda: 0)

    if WATCH_ADDRESS is not None:
        print(f'Watching address {WATCH_ADDRESS}')

    while True:
        data = indexer_client.search_transactions_by_address(address=POOL_ADDRESS,
                                                             next_page=next_token)
        txns = data['transactions']
        print(f'New txns, cnt = {len(txns)}')

        for tx in txns:
            if ASSET_TRANSFER_TX in tx:
                if tx['confirmed-round'] > MAX_ROUND:
                    continue

                sender = tx['sender']
                amount = tx[ASSET_TRANSFER_TX]['amount']
                if sender == WATCH_ADDRESS:
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
                        if inner_tx['confirmed-round'] > MAX_ROUND:
                            print(inner_tx)
                            continue

                        receiver = inner_tx[ASSET_TRANSFER_TX]['receiver']
                        amount = inner_tx[ASSET_TRANSFER_TX]['amount']
                        if receiver == WATCH_ADDRESS:
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

    res_filename = f'opyx_pool_{MAX_ROUND}.json'
    with open(res_filename, 'w') as write_file:
        json.dump(balances, write_file, indent=4, sort_keys=True)

    print(f'{len(all_txns)} processed!')
    print(f'{len(balances)} wallets are written to "{res_filename}"!')

    total_microtokens = 0
    for k, v in balances.items():
        total_microtokens += v

    print(f'In total {total_microtokens} microtokens')


