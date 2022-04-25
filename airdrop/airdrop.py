from datetime import datetime

from algosdk import mnemonic, account
from algosdk.future import transaction
from algosdk.v2client import algod
from pymongo import MongoClient

from env import MONGO_PORT, DB_NAME, settings, META_TOTAL_SUPPLY

TOTAL_AIRDROPS = 12
TOTAL_PERCENT = 0.03

META_ASA_ID = 123  # TODO

CURRENT_PERCENT = TOTAL_PERCENT / TOTAL_AIRDROPS
CURRENT_SUPPLY = META_TOTAL_SUPPLY * CURRENT_PERCENT


db = MongoClient(port=MONGO_PORT)[DB_NAME]

algod_client = algod.AlgodClient(settings.algod_token, settings.algod_address,
                                 headers={
                                     'User-Agent': 'py-algorand-sdk',
                                     'X-API-Key': settings.algod_token
                                 })
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def send_tokens(address: str, amount: float, airdrop_id: str):
    done = db.airdrops.find_one({'airdrop_id': airdrop_id, 'address': address})
    if done is not None:
        print(f'Already sent {amount} to {address} before!')
        return

    print(f'Sending {amount} META to {address}!')
    params = algod_client.suggested_params()

    unsigned_txn = transaction.AssetTransferTxn(
        sender=public_key,
        sp=params,
        receiver=address,
        amt=amount,
        index=META_ASA_ID,
        note=f'Metapunks Airdrop #{airdrop_id}'
    )
    signed_txn = unsigned_txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)

    db.airdrops.insert_one(
        {
            'airdrop_id': airdrop_id,
            'address': address,
            'amount': amount,
            'txid': txid,
            'time': datetime.now()
        }
    )

    transaction.wait_for_confirmation(algod_client, txid, 4)

    print(f'Sent with {txid}!')


def run(airdrop_id: str):
    print(f'Airdrop #{airdrop_id} in progress!')

    snapshot = db.snapshots.find_one({'snapshot_id': airdrop_id})
    nft_count = snapshot['nft_count']
    print(f'Total {nft_count} NFTs!')

    tokens_per_nft = CURRENT_SUPPLY / nft_count
    print(f'{tokens_per_nft} META per NFT!')

    amount_sent = 0

    for holder in snapshot['holders']:
        amount = tokens_per_nft * len(holder['asa_ids'])
        send_tokens(holder['address'], amount, airdrop_id)
        amount_sent += amount

    print(f'Sent {amount_sent} tokens!')

