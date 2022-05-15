from datetime import datetime

from algosdk import mnemonic, account
from algosdk.future import transaction
from algosdk.v2client import algod
from pymongo import MongoClient

from blockchain.assets import META_TOTAL_SUPPLY, META_ASA_ID, META_DECIMALS
from dexes.tinyman import tinyman_from_algod
from env import settings

TOTAL_AIRDROPS = 12
TOTAL_PERCENT = 0.03

CURRENT_PERCENT = TOTAL_PERCENT / TOTAL_AIRDROPS
AIRDROP_SUPPLY = META_TOTAL_SUPPLY * CURRENT_PERCENT


db = MongoClient(port=settings.mongodb_port)[settings.db_name]

algod_client = algod.AlgodClient(settings.algod_token, settings.algod_address,
                                 headers={
                                     'User-Agent': 'py-algorand-sdk',
                                     'X-API-Key': settings.algod_token
                                 })
tinyman_client = tinyman_from_algod(algod_client)
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def send_tokens(address: str, amount: float, airdrop_id: str) -> float:
    done = db.airdrops.find_one({'airdrop_id': airdrop_id, 'address': address})
    if done is not None:
        print(f'Already sent {amount} to {address} before!')
        return 0

    print(f'Sending {amount} META to {address}!')
    amount_micros = int(amount * (10 ** META_DECIMALS))

    params = algod_client.suggested_params()
    unsigned_txn = transaction.AssetTransferTxn(
        sender=public_key,
        sp=params,
        receiver=address,
        amt=amount_micros,
        index=META_ASA_ID,
        note=f'Metapunks Airdrop #{airdrop_id}'
    )
    signed_txn = unsigned_txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)

    transaction.wait_for_confirmation(algod_client, txid, 4)

    db.airdrops.insert_one(
        {
            'airdrop_id': airdrop_id,
            'address': address,
            'amount': amount,
            'txid': txid,
            'time': datetime.now()
        }
    )

    print(f'Sent with {txid}!')

    return amount


def filter_opted_in(airdrop_id: str, holders):
    res = []
    for holder in holders:
        address = holder['address']
        if tinyman_client.asset_is_opted_in(META_ASA_ID, address):
            record = {
                'airdrop_id': airdrop_id,
                'address': address,
                'nft_cnt': len(holder['asa_ids'])
            }
            res.append(record)
            db.opted_in.insert_one(record)
    return res


def run(airdrop_id: str):
    print(f'Airdrop #{airdrop_id} in progress!')

    snapshot = db.snapshots.find_one({'snapshot_id': airdrop_id})

    nft_count = snapshot['nft_count']
    print(f'Total {nft_count} NFTs!')

    holders = snapshot['holders']
    print(f'Total {len(holders)} holders!')

    opted_in = filter_opted_in(airdrop_id, holders)
    print(f'Total {len(opted_in)} holders are opted-in!')

    total_nfts = 0
    for holder in opted_in:
        total_nfts += holder['nft_cnt']
    print(f'Total {total_nfts} opted-in NFTs!')

    tokens_per_nft = AIRDROP_SUPPLY / total_nfts
    print(f'Total {AIRDROP_SUPPLY} tokens, {tokens_per_nft} META per NFT!\n')

    amount_sent = 0
    holders_sent = 0

    for holder in opted_in:
        amount = tokens_per_nft * holder['nft_cnt']
        address = holder['address']
        try:
            amount = send_tokens(address, amount, airdrop_id)
            amount_sent += amount
            holders_sent += 1
            print(f'Sent {amount} to {address}')
        except Exception as e:
            print(e, '\n', holder)

    print(f'Sent {amount_sent} tokens to {holders_sent} holders!')


