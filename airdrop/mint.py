import json

from algosdk import mnemonic, account
from algosdk.future import transaction
from algosdk.v2client import algod

from blockchain.node import print_created_asset
from env import settings, META_TOTAL_SUPPLY, META_DECIMALS

algod_client = algod.AlgodClient(settings.algod_token, settings.algod_address,
                                 headers={
                                     'User-Agent': 'py-algorand-sdk',
                                     'X-API-Key': settings.algod_token
                                 })
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)


def mint_token() -> int:
    params = algod_client.suggested_params()
    total_units = META_TOTAL_SUPPLY * (10 ** META_DECIMALS)
    unsigned_txn = transaction.AssetCreateTxn(
        sender=public_key,
        sp=params,
        total=total_units,
        decimals=META_DECIMALS,
        default_frozen=False,
        unit_name='META',
        asset_name='Cometa',
        manager=public_key,
        reserve=public_key,
        freeze=public_key,
        clawback=public_key,
        url='https://cometa.farm/'
    )

    signed_txn = unsigned_txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)

    print(f'txid = {txid}')

    confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 4)

    print(f'Transaction information: {json.dumps(confirmed_txn, indent=4)}')

    ptx = algod_client.pending_transaction_info(txid)
    asset_id = ptx['asset-index']
    print_created_asset(algod_client, public_key, asset_id)

    return asset_id


if __name__ == '__main__':
    print(mint_token())
