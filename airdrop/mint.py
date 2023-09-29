import json

from algosdk import mnemonic, account
from algosdk.future import transaction

from blockchain.assets import META_TOTAL_SUPPLY, META_DECIMALS, META_ASA_ID
from blockchain.node import print_created_asset, init_algod_client
from env import settings

algod_client = init_algod_client()
private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)

rekeyed_private_key = mnemonic.to_private_key(settings.rekeyed_mnemonic)


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


def change_meta_config():
    params = algod_client.suggested_params()
    txn = transaction.AssetConfigTxn(
        sender=public_key,
        sp=params,
        index=META_ASA_ID,
        manager=public_key,
        reserve='3IX4JSNWFQAH55TKFLWGW7EVCGMDDKW3EEWLDDUME7J7H72LSQCUFWXJTY',
        freeze=None,
        clawback=None,
        strict_empty_address_check=False)
    signed_txn = txn.sign(rekeyed_private_key)
    txid = algod_client.send_transaction(signed_txn)
    confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 4)
    print_created_asset(algod_client, public_key, META_ASA_ID)


if __name__ == '__main__':
    change_meta_config()
