import requests

BASE_URL = 'https://node.algoexplorerapi.io'


def get_current_round():
    url = f'{BASE_URL}/v2/status'
    data = requests.get(url).json()
    return data['last-round']
