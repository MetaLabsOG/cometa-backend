import time
from dataclasses import dataclass
from typing import List, Optional, Dict

from api import tinychart
from api.tinychart import Price
from blockchain.assets import MICROALGOS_IN_ALGO
from blockchain.indexer import get_account_assets
from dexes.tinyman import get_all_assets, get_asset_info


@dataclass
class AssetInfo:
    name: str
    ticker: str
    amount: int
    price: Price
    asset_id: int


def get_wallet_assets(address: str) -> List[AssetInfo]:
    wallet_assets = get_account_assets(address)
    res = []
    for asset in wallet_assets:
        asset_id = asset['asset-id']
        asset_info = get_asset_info(asset_id)
        if asset_info is not None and asset['amount'] and not asset['deleted']:
            asset_amount = asset['amount'] / 10 ** asset_info['decimals']
            asset_price = tinychart.get_asset_price_full(asset_id)
            res.append(
                AssetInfo(
                    asset_info['name'],
                    asset_info['unit_name'],
                    asset_amount,
                    asset_price,
                    asset_id
                )
            )

    return res


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
    # TODO: implement
    if address == 'null':
        return []
    algo_price = tinychart.get_algo_price()
    return [
        NftInfo(
            284290866,
            'Yieldling Rare #013',
            'Yieldlings',
            'https://ipfs.io/ipfs/bafkreifrnteqwajm53rshk654c3bhz6vdoyduegz5xsqfohft5zq5rpomy',
            Price(1500 * algo_price, 1500 * MICROALGOS_IN_ALGO),
            14.5
        ),
        NftInfo(
            359028119,
            'M.N.G.O #1540',
            'M.N.G.O',
            'https://ipfs.io/ipfs/QmU9etNk15tZKXug4qEL6YDRQPEUhY67yZ1prFXvzmULpo',
            Price(1000 * algo_price, 1000 * MICROALGOS_IN_ALGO),
            -8.2
        ),
        NftInfo(
            391839995,
            'Pixel Guy #128',
            'Pixel Guys',
            'https://ipfs.io/ipfs/QmNNffZu5wYHKjfpxwpKHXF79sbbe2boz2fwU5gEyy7ArZ/128.png',
            Price(70 * algo_price, 70 * MICROALGOS_IN_ALGO),
            -60.7
        ),
        NftInfo(
            656165674,
            'Astro #170',
            'AlgoAstros',
            'https://ipfs.io/ipfs/bafkreif6tzey3lh5yszyhtnr3lmh6lcdpx5txcm34ovlbnwujfb2sd24fa',
            Price(999 * algo_price, 999 * MICROALGOS_IN_ALGO),
            -13.1
        ),
        NftInfo(
            708186273,
            'FC1662',
            'Flemish Clones',
            'https://ipfs.infura.io/ipfs/QmNdD53TzNc5AoGuD51EnkUQYHgxU9iDX7PeGL9U8htJkG',
            Price(185 * algo_price, 185 * MICROALGOS_IN_ALGO),
            5.5
        ),
        NftInfo(
            779735087,
            'Shep #5872',
            'Shep',
            'https://ipfs.io/ipfs/QmcVKMJHVPHgg8sqskfDzk9a3nTH7LeLTVNmHnYtsTzXtc',
            Price(293 * algo_price, 293 * MICROALGOS_IN_ALGO),
            -7.7
        ),
        NftInfo(
            834757311,
            'Fracctal Tamer 024',
            'Fracctal Tamers',
            'https://ipfs.io/ipfs/bafybeicobcmmyunmkliogvs7rjopckd5uhsrzcs2ppfxlworojxome54di',
            Price(279 * algo_price, 279 * MICROALGOS_IN_ALGO),
            4.5
        )
    ]


# TODO: replace with get_wallet_assets with param 'get_price'
def get_wallet_assets2(address: str) -> Dict[str, AssetInfo]:
    assets_info = get_all_assets()
    assets = get_account_assets(address)

    wallet_assets = {}
    for asset in assets:
        asset_id = asset['asset-id']
        if str(asset_id) in assets_info and asset['amount'] and not asset['deleted']:
            asset_info = assets_info[str(asset_id)]
            asset_amount = asset['amount'] / 10 ** asset_info['decimals']
            # asset_price = get_asset_price(asset_id)
            wallet_assets[str(asset_id)] = AssetInfo(asset_info['name'], asset_info['unit_name'], asset_amount, 0, asset_id)

    return wallet_assets
