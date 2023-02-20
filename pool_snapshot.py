import json
from collections import defaultdict

from algosdk.v2client import indexer

indexer_client = indexer.IndexerClient(indexer_token='', indexer_address='https://algoindexer.algoexplorerapi.io/')

POOL_ADDRESS = 'P2MVQM57OYFSAKAHYCKJVV4Q4CEFHKITJ6NDTNERVMYVLTCQ4Q6SZ5D5VM'
ASSET_TRANSFER_TX = 'asset-transfer-transaction'
APPLICATION_CALL_TX = 'application-transaction'
PAYMENT_TX = 'payment-transaction'


if __name__ == '__main__':
    next_token = None
    all_txns = []
    current_round = 0

    balances = defaultdict(lambda: 0)

    while True:
        data = indexer_client.search_transactions_by_address(address=POOL_ADDRESS,
                                                             next_page=next_token)
        txns = data['transactions']
        print(f'New txns, cnt = {len(txns)}')

        current_round = data['current-round']
        print(f'Current round = {current_round}')

        for tx in txns:
            if ASSET_TRANSFER_TX in tx:
                sender = tx['sender']
                amount = tx[ASSET_TRANSFER_TX]['amount']
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
                        receiver = inner_tx[ASSET_TRANSFER_TX]['receiver']
                        amount = inner_tx[ASSET_TRANSFER_TX]['amount']
                        balances[receiver] -= amount

        print(f'{len(txns)} txns processed!')
        print(f'Currently {len(balances)} balances')
        print()

        all_txns.extend(txns)
        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    with open(f'cosmic_stakes_{current_round}.json', 'w') as write_file:
        json.dump(balances, write_file, indent=4, sort_keys=True)

    print(f'{len(all_txns)} processed!')
    print(f'{len(balances)} wallets are written to "cosmic_snapshot.json"!')

    total_microtokens = 0
    for k, v in balances.items():
        total_microtokens += v

    print(f'In total {total_microtokens} microtokens')


