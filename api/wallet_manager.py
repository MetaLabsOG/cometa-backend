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
ALGO_PRICE = 0.89


def get_wallet_assets(address: str) -> List[AssetInfo]:
    # TODO: implement
    return [
        AssetInfo('USD Coin', 'USDC', 1000, Price(1, 1111000)),
        AssetInfo('Algorand', 'ALGO', 2000, Price(0.89, 1000000)),
        AssetInfo('Defly Token', 'DEFLY', 42000, Price(0.0139, 12800))
    ]


# TODO: name sucks
@dataclass
class TimedCost:
    timestamp: int
    cost: Price


def get_wallet_total_cost(address: str, weeks_count: int) -> List[TimedCost]:
    WEEK_SECONDS = 604800
    MAX_COST = 9000000000  # 10^10
    cur_time = int(time.time())
    costs = []
    for i in range(0, weeks_count):
        price = MAX_COST * (weeks_count - i) // weeks_count
        cost = TimedCost(cur_time, Price(price * ALGO_PRICE / MICROALGOS_IN_ALGO, price))
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
    return [
        NftInfo(
            575429743,
            'Dead Putin Society  # 23',
            'Dead Putin Society',
            'https://ipfs.io/ipfs/bafybeieibt23cenmgkzaqj67b6ebgxn5nkr7nfe3jqysg7nrjf2sue6ppm#i',
            Price(10 * ALGO_PRICE, 10 * MICROALGOS_IN_ALGO)
        ),
        NftInfo(
            471833050,
            'Metapunk #5',
            'Metapunks',
            'https://arweave.net/Il3cm3qrbuyqhVHIaYTh0BFoYr3Ytsdc8ST-lczPbaQ',
            Price(75 * ALGO_PRICE, 75 * MICROALGOS_IN_ALGO),
            0.08
        )
    ]
