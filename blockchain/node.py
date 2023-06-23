import json

import requests
from algosdk.v2client.algod import AlgodClient
from cachetools import cached, TTLCache

from env import settings

BASE_URL = 'https://mainnet-api.algonode.cloud"'


# TODO: maybe inject settings?
def init_algod_client() -> AlgodClient:
    return AlgodClient(settings.algod_token, settings.algod_address,
                       headers={
                           'User-Agent': 'py-algorand-sdk',
                           'X-API-Key': settings.algod_token
                       })


algod_client = init_algod_client()


@cached(cache=TTLCache(maxsize=1, ttl=settings.block_time))
def get_current_round():
    data = algod_client.status()
    return data['last-round']


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
