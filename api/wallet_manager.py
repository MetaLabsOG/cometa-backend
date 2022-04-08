import time
from dataclasses import dataclass
from typing import List

from env import MICROALGOS_IN_ALGO


@dataclass
class Price:
    usd: float
    microalgo: int


@dataclass
class WalletAsset:
    name: str
    ticker: str
    amount: int
    price: Price


# TODO: get ALGO price
ALGO_PRICE = 0.89


def get_wallet_assets(address: str) -> List[WalletAsset]:
    # TODO: implement
    return [
        WalletAsset('USD Coin', 'USDC', 1000, Price(1, 1111000)),
        WalletAsset('Algorand', 'ALGO', 2000, Price(0.89, 1000000)),
        WalletAsset('Defly Token', 'DEFLY', 42000, Price(0.0139, 128000))
    ]


# TODO: name sucks
@dataclass
class TimedCost:
    timestamp: int
    cost: Price


def get_wallet_total_cost(address: str, weeks_count: int):
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
