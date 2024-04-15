from algosdk import mnemonic, account, transaction

from blockchain.node import init_algod_client
from env import settings

algod_client = init_algod_client()
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def opt_in(asa_ids: list[int]):
    for asa_id in asa_ids:
        params = algod_client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=public_key,
            sp=params,
            receiver=public_key,
            amt=0,
            index=asa_id)

        signed_txn = txn.sign(private_key)
        txid = algod_client.send_transaction(signed_txn)

        print(f'txid = {txid}')

        confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 3)


asa_ids = [
    976584825,
    976587029,
    976588947,
976590048,
976591691,
976593947,
976593947,
976596812,
976598073,
976599867,
976601214,
976602491
]

if __name__ == '__main__':
    opt_in(asa_ids)
