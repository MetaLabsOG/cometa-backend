from algosdk import mnemonic, account, transaction

from blockchain.node import init_algod_client
from env import settings

algod_client = init_algod_client()
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def send_nfts(asa_ids: list[int], receiver: str):
    print(f'Sending in {asa_ids}...\n')
    for ind, asa_id in enumerate(asa_ids):
        print(f'#{ind}/{len(asa_ids)} Sending in {asa_id}...')
        params = algod_client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=public_key,
            sp=params,
            receiver=receiver,
            amt=1,
            index=asa_id
        )

        signed_txn = txn.sign(private_key)
        txid = algod_client.send_transaction(signed_txn)

        confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 3)
        print(f'Sent with txid = {txid}')


RECEIVER = 'METALOLV7YCMDNYKX6QBDHQV33Y7HE6KEKWHJRPHOFUIB4BKV3F4EU4MMQ'
ASA_IDS = [
    508894655,
    843731043,
    871459329
]

if __name__ == '__main__':
    send_nfts(ASA_IDS, RECEIVER)
