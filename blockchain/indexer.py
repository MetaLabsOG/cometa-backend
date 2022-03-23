import requests

BASE_URL = 'https://algoexplorerapi.io/idx2'


def get_asset_creator(asset_id: int) -> str:
    url = f'{BASE_URL}/v2/assets/{asset_id}'
    # TODO: cache asset data
    data = requests.get(url).json()
    return data['asset']['params']['creator']


if __name__ == '__main__':
    print(get_asset_creator(485475194))
