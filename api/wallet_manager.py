import time
from dataclasses import dataclass
from typing import List, Optional

from env import MICROALGOS_IN_ALGO


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


# TODO: get ALGO price
ALGO_PRICE = 0.75


def get_wallet_assets(address: str) -> List[AssetInfo]:
    # TODO: implement
    if address == 'null':
        return []
    return [
        AssetInfo('USD Coin', 'USDC', 1589, Price(1, int(1 / ALGO_PRICE * MICROALGOS_IN_ALGO))),
        AssetInfo('Algorand', 'ALGO', 15100, Price(ALGO_PRICE, MICROALGOS_IN_ALGO)),
    ]


# TODO: name sucks
@dataclass
class TimedCost:
    timestamp: int
    cost: Price


def get_wallet_total_cost(address: str, weeks_count: int) -> List[TimedCost]:
    WEEK_SECONDS = 604800
    MAX_COST = (15100 + 1589 + 800 + 700 + 150) * MICROALGOS_IN_ALGO
    cur_time = int(time.time())
    costs = []
    for i in range(0, weeks_count):
        price = MAX_COST * (weeks_count - i) // weeks_count
        cost = TimedCost(cur_time, Price(price * ALGO_PRICE / MICROALGOS_IN_ALGO, price))
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
    return [
        NftInfo(
            284290866,
            'Yieldling Rare #013',
            'Yieldlings',
            'https://ipfs.io/ipfs/bafkreifrnteqwajm53rshk654c3bhz6vdoyduegz5xsqfohft5zq5rpomy',
            Price(800 * ALGO_PRICE, 800 * MICROALGOS_IN_ALGO)
        ),
        NftInfo(
            359028119,
            'M.N.G.O #1540',
            'M.N.G.O',
            'https://ipfs.io/ipfs/QmU9etNk15tZKXug4qEL6YDRQPEUhY67yZ1prFXvzmULpo',
            Price(700 * ALGO_PRICE, 700 * MICROALGOS_IN_ALGO),
            0.08
        ),
        NftInfo(
            391839995,
            'Pixel Guy #128',
            'Pixel Guys',
            'https://ipfs.io/ipfs/QmNNffZu5wYHKjfpxwpKHXF79sbbe2boz2fwU5gEyy7ArZ/128.png',
            Price(150 * ALGO_PRICE, 150 * MICROALGOS_IN_ALGO),
            -0.2
        )
    ]
