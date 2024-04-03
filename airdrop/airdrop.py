import json
from datetime import datetime
from math import sqrt

from algosdk import mnemonic, account, transaction
from pymongo import MongoClient

from blockchain.assets import META_ASA_ID, META_DECIMALS
from blockchain.node import init_algod_client
from dexes.tinyman import tinyman_from_algod
from env import settings

AIRDROP_SUPPLY = 10000

db = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)[settings.db_name]

algod_client = init_algod_client()
tinyman_client = tinyman_from_algod(algod_client)
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def send_meta_tokens(address: str, amount: float, airdrop_id: str) -> float:
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
        note=f'❤️ from Cometa to Algofi and its users!'
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
            'time': datetime.now().timestamp()
        }
    )

    print(f'Sent with {txid}!')

    return amount


def filter_opted_in(airdrop_id: str, addresses: list[str]):
    res = []
    for address in addresses:
        if tinyman_client.asset_is_opted_in(META_ASA_ID, address):
            res.append(address)
    return res


def run(airdrop_id: str):
    print(f'Airdrop #{airdrop_id} in progress!')

    snapshot_json = json.load(open(f'snapshot_{airdrop_id}.json'))
    holders_dict = snapshot_json['holders']

    to_airdrop = {}
    for address, asa_ids in holders_dict.items():
        if tinyman_client.asset_is_opted_in(META_ASA_ID, address):
            to_airdrop[address] = asa_ids

    print(f'Total {len(to_airdrop)} addresses are opted-in!')

    address_count = {}

    total_count = 0
    for address, asa_ids in to_airdrop.items():
        cnt = int(sqrt(len(asa_ids)) + 0.5)
        address_count[address] = cnt
        total_count += cnt

    tokens_per_part = AIRDROP_SUPPLY / total_count
    print(f'Total {AIRDROP_SUPPLY} tokens, {tokens_per_part} META per part!\n')

    amount_sent = 0
    addrs_sent = 0

    for address, count in address_count.items():
        try:
            address_amount = count * tokens_per_part
            amount = send_meta_tokens(address, address_amount, airdrop_id)
            amount_sent += amount
            addrs_sent += 1
            print(f'Sent {amount} to {address}')
        except Exception as e:
            print(e, '\n', address)

    print(f'Sent {amount_sent} tokens to {addrs_sent} holders!')


if __name__ == '__main__':
    run('comeback_2')
