import requests

BASE_URL = 'https://algoexplorerapi.io/idx2'


def get_asset(asset_id: int):
    # TODO: cache asset data
    url = f'{BASE_URL}/v2/assets/{asset_id}'
    return requests.get(url).json()['asset']


def get_asset_creator(asset_id: int) -> str:
    asset = get_asset(asset_id)
    return asset['params']['creator']


def get_asset_owner(asset_id: int) -> str:
    url = f'{BASE_URL}/v2/assets/{asset_id}/balances'
    data = requests.get(url).json()
    balances = data['balances']
    for balance in balances:
        if balance['amount'] == 1:
            return balance['address']
    raise Exception(f'Asset {asset_id} has all zero balances')


def get_asset_ids_by_creator(address):
    URL = f'{BASE_URL}/v2/assets?creator={address}'
    asset_ids = []
    data = {}
    PARAMS = {}

    for i in range(100):
        if data and data['next-token']:
            PARAMS = {'next': data['next-token']}
        r = requests.get(url=URL, params=PARAMS)
        data = r.json()
        for asset in data['assets']:
            asset_ids.append(asset['index'])
        if not data.get('next-token', None):
            break

    return asset_ids


if __name__ == '__main__':
    print(get_asset_creator(485475194))
