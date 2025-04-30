import json
from base64 import b64decode

from algosdk import mnemonic, account, transaction
from algosdk.v2client.algod import AlgodClient
from algosdk.error import AlgodHTTPError
from cachetools import cached, TTLCache
import logging

from env import settings


# TODO: maybe inject settings?
def init_algod_client() -> AlgodClient:
    return AlgodClient(settings.algod_token, settings.algod_address,
                       headers={
                           'User-Agent': 'py-algorand-sdk',
                           'x-algo-api-token': settings.algod_token
                       })


algod_client = init_algod_client()


@cached(cache=TTLCache(maxsize=1, ttl=settings.block_time))
def get_current_round():
    try:
        data = algod_client.status()
        return data['last-round']
    except AlgodHTTPError as e:
        logging.error(f"Failed to get current round from Algod: {e}")
        # Return a sensible default or re-raise a different exception if needed
        # For now, returning None or a default round might prevent crashes downstream
        # but could lead to unexpected behavior. Returning 0 might be safest if
        # downstream code expects an int, but be aware of the implications.
        return 0 # Or None, or raise custom error


# fast copypaste
#   Utility function used to print created asset for account and assetid
def print_created_asset(algodclient, account, assetid):
    # note: if you have an indexer instance available it is easier to just use this
    # response = myindexer.accounts(asset_id = assetid)
    # then use 'account_info['created-assets'][0] to get info on the created asset
    account_info = algodclient.account_info(account)
    idx = 0
    for my_account_info in account_info['created-assets']:
        scrutinized_asset = account_info['created-assets'][idx]
        idx = idx + 1
        if (scrutinized_asset['index'] == assetid):
            print("Asset ID: {}".format(scrutinized_asset['index']))
            print(json.dumps(my_account_info['params'], indent=4))
            break


#   Utility function used to print asset holding for account and assetid
def print_asset_holding(algodclient, account, assetid):
    # note: if you have an indexer instance available it is easier to just use this
    # response = myindexer.accounts(asset_id = assetid)
    # then loop thru the accounts returned and match the account you are looking for
    account_info = algodclient.account_info(account)
    idx = 0
    for my_account_info in account_info['assets']:
        scrutinized_asset = account_info['assets'][idx]
        idx = idx + 1
        if scrutinized_asset['asset-id'] == assetid:
            print("Asset ID: {}".format(scrutinized_asset['asset-id']))
            print(json.dumps(scrutinized_asset, indent=4))
            break


def try_rekeyed_transaction():
    algod_client = init_algod_client()
    params = algod_client.suggested_params()

    private_key = mnemonic.to_private_key(settings.algo_mnemonic)
    public_key = account.address_from_private_key(private_key)

    rekeyed_private_key = mnemonic.to_private_key(settings.rekeyed_mnemonic)
    rekeyed_public_key = account.address_from_private_key(rekeyed_private_key)

    unsigned_txn = transaction.PaymentTxn(
        sender=public_key,
        sp=params,
        receiver='METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM',
        amt=1000000,
        note=b"Checking rekeyed txn.",
    )
    signed_txn = unsigned_txn.sign(rekeyed_private_key)
    txid = algod_client.send_transaction(signed_txn)
    print("Successfully submitted transaction with txID: {}".format(txid))

    # wait for confirmation
    txn_result = transaction.wait_for_confirmation(algod_client, txid, 4)

    print(f"Transaction information: {json.dumps(txn_result, indent=4)}")
    print(f"Decoded note: {b64decode(txn_result['txn']['txn']['note'])}")
