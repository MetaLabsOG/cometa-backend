import time
from dataclasses import dataclass
from typing import List, Optional, Dict
import requests
import urllib.request, json

from api import tinychart
from blockchain.assets import MICROALGOS_IN_ALGO
from dexes.tinyman import get_price_algo, init_tinyman_client
from env import settings

ASSETS_PATH = 'https://asa-list.tinyman.org/assets.json'
ACCOUNT_API = 'https://algoindexer.algoexplorerapi.io/v2/accounts/' if settings.is_mainnet() \
    else 'https://algoindexer.testnet.algoexplorerapi.io/v2/accounts/'


@dataclass
class Price:
    usd: float
    microalgo: int


@dataclass
class AssetInfo:
    name: str
    ticker: str
    amount: int
    price: Price
    asset_id: int


def get_wallet_assets(address: str) -> List[AssetInfo]:
    # TODO: implement
    if address == 'null':
        return []
    algo_price = tinychart.get_algo_price()
    DEFLY_IN_ALGO = 0.0088
    return [
        AssetInfo('USD Coin', 'USDC', 1589, Price(1, int(1 / algo_price * MICROALGOS_IN_ALGO)), 31566704),
        AssetInfo('Algorand', 'ALGO', 13750, Price(algo_price, MICROALGOS_IN_ALGO), 0), # TODO: next two lines insted of this when front is fixed
        # AssetInfo('Algorand', 'ALGO', 12625, Price(algo_price, MICROALGOS_IN_ALGO)),
        # AssetInfo('gALGO3', 'gALGO3', 1125, Price(algo_price, MICROALGOS_IN_ALGO)),
        AssetInfo('Defly Token', 'DEFLY', 24672, Price(algo_price * DEFLY_IN_ALGO, DEFLY_IN_ALGO * MICROALGOS_IN_ALGO), 470842789),
    ]


# TODO: name sucks
@dataclass
class TimedCost:
    timestamp: int
    cost: Price


def get_wallet_total_cost(address: str, weeks_count: int) -> List[TimedCost]:
    # TODO: I should never write code again
    WEEK_SECONDS = 604800
    MAX_COST = (12851 + 1589 + 1125 + 1000 + 700 + 350 + 850) * MICROALGOS_IN_ALGO
    algo_price = tinychart.get_algo_price()
    ALGO_PRICE_WEEKS = [algo_price, 0.77, 0.83, 0.9, 0.74, 0.7]  # 22.04, 17.04, 9.04, 1.04, 24.03, 16.03
    TOTAL_COST_WEEKS = [MAX_COST * algo for algo in ALGO_PRICE_WEEKS]
    cur_time = int(time.time())
    costs = []
    for i in range(0, weeks_count):
        cost = TimedCost(cur_time, Price(TOTAL_COST_WEEKS[i] / MICROALGOS_IN_ALGO, int(TOTAL_COST_WEEKS[i] / algo_price)))
        if address == 'null':
            cost = TimedCost(cur_time, Price(0, 0))
        costs.append(cost)
        cur_time -= WEEK_SECONDS
    return costs[::-1]


@dataclass
class NftInfo:
    asa_id: int
    name: str
    collection: str
    image_url: str
    floor_price: Price
    week_price_change: Optional[float] = None


def get_wallet_nfts(address: str) -> List[NftInfo]:
    if address == 'null':
        return []
    algo_price = tinychart.get_algo_price()
    return [
        NftInfo(
            284290866,
            'Yieldling Rare #013',
            'Yieldlings',
            'https://ipfs.io/ipfs/bafkreifrnteqwajm53rshk654c3bhz6vdoyduegz5xsqfohft5zq5rpomy',
            Price(1000 * algo_price, 1000 * MICROALGOS_IN_ALGO),
            -12
        ),
        NftInfo(
            359028119,
            'M.N.G.O #1540',
            'M.N.G.O',
            'https://ipfs.io/ipfs/QmU9etNk15tZKXug4qEL6YDRQPEUhY67yZ1prFXvzmULpo',
            Price(700 * algo_price, 700 * MICROALGOS_IN_ALGO),
            -8
        ),
        NftInfo(
            391839995,
            'Pixel Guy #128',
            'Pixel Guys',
            'https://ipfs.io/ipfs/QmNNffZu5wYHKjfpxwpKHXF79sbbe2boz2fwU5gEyy7ArZ/128.png',
            Price(350 * algo_price, 350 * MICROALGOS_IN_ALGO),
            -60
        ),
        NftInfo(
            656165674,
            'Astro #170',
            'AlgoAstros',
            'https://ipfs.io/ipfs/bafkreif6tzey3lh5yszyhtnr3lmh6lcdpx5txcm34ovlbnwujfb2sd24fa',
            Price(850 * algo_price, 850 * MICROALGOS_IN_ALGO),
            -12
        )
    ]


def get_asset_price(asset_id: int) -> Price:
    tinyman_client = init_tinyman_client()
    # TODO: cache for sure (5 min (set in settings))
    price_algo = get_price_algo(tinyman_client, asset_id)
    algo_price = tinychart.get_algo_price()
    return Price(price_algo * algo_price, int(price_algo * MICROALGOS_IN_ALGO))


def get_wallet_assets2(address: str) -> Dict[str, AssetInfo]:
    with urllib.request.urlopen(ASSETS_PATH) as url:
        assets_info = json.loads(url.read().decode())

    url = ACCOUNT_API + address
    r = requests.get(url)
    data = r.json()

    assets = data['account']['assets']
    assets.append({
        'asset-id': 0,
        'amount': data['account']['amount'],
        'deleted': False
    })

    wallet_assets = {}
    for asset in assets:
        asset_id = asset['asset-id']
        if str(asset_id) in assets_info and asset['amount'] and not asset['deleted']:
            asset_info = assets_info[str(asset_id)]
            asset_amount = asset['amount'] / 10 ** asset_info['decimals']
            # asset_price = get_asset_price(asset_id)
            wallet_assets[str(asset_id)] = AssetInfo(asset_info['name'], asset_info['unit_name'], asset_amount, 0, asset_id)

    return wallet_assets
