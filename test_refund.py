from algosdk import transaction, mnemonic, account
from algosdk.v2client import indexer, algod

ALGOD_URL = "https://mainnet-api.4160.nodely.io"
INDEXER_URL = "https://mainnet-idx.4160.nodely.io"

ALGOD_TOKEN="1662392EA93E328AFD10BDDA54D5A80C"
INDEXER_TOKEN = ALGOD_TOKEN

algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_URL)
indexer_client = indexer.IndexerClient(INDEXER_TOKEN, INDEXER_URL)


def get_transactions(address):
    response = indexer_client.search_transactions_by_address(address)
    return response['transactions']

def send_algo_transaction(sender, receiver, amount, private_key):
    params = algod_client.suggested_params()
    txn = transaction.PaymentTxn(sender, params, receiver, amount)
    signed_txn = txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)
    return txid


def send_asset_transaction(sender, receiver, asset_id, amount, private_key):
    params = algod_client.suggested_params()
    txn = transaction.AssetTransferTxn(sender, params, receiver, amount, asset_id)
    signed_txn = txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)
    return txid


mnemonic_phrase = 'tortoise arrest gas marriage film pond tired absurd gentle phone cancel oak army total flush flag fatal settle answer vast coin setup depart abstract vault'
private_key = mnemonic.to_private_key(mnemonic_phrase)
address = account.address_from_private_key(private_key)
except_addresses = [
    address,
    '6GIWLJFFJDBMFSBCYC5G5WG5QKCXZF7IZPO6NU6WFVAJ2MLYDYDK5GOWN4',
    'Y5UEPEGMIGH3FHXA3R62DTRB5BJXZVLB3HKNKARFDSBIJT34IICGB7GOFU',
    'ETD7OQJ4BUKQOHGTI2JUPLZBAC3YE2SFY5X4AYAMYS6ODXKMMDHKTI3YK4',
    'B6U5HPVUMR2G7VV7DF5SRXRXI6M6UDVQVX4I6EV3NEVIBDBOJRBTKXWC5E'
]

error_txns = []

def main():
    transactions = get_transactions(address)
    for txn in transactions:
        try:
            sender = txn['sender']
            if sender not in except_addresses:
                if 'asset-transfer-transaction' in txn:
                    asset_id = txn['asset-transfer-transaction']['asset-id']
                    # amount = txn['asset-transfer-transaction']['amount']
                    # receiver = txn['asset-transfer-transaction']['receiver']
                    # txid = send_asset_transaction(address, sender, asset_id, amount, private_key)
                    # print(f"Transaction {txid} sent to {sender}")
                elif 'payment-transaction' in txn:
                    amount = txn['payment-transaction']['amount']
                    receiver = txn['payment-transaction']['receiver']
                    txid = send_algo_transaction(address, sender, amount, private_key)
                    print(f"Transaction {txid} sent to {sender}")
                else:
                    print("\nWTF\nTransaction type not supported")
        except Exception as e:
            error_txns.append(txn)
            print(f"Error: {e}")

    print(f"Error transactions {len(error_txns)}: {error_txns}")


if __name__ == "__main__":
    main()
