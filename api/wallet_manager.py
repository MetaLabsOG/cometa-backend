from dataclasses import dataclass
from typing import List


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


def get_wallet_assets(address: str) -> List[WalletAsset]:
    # TODO: implement
    return [
        WalletAsset('USD Coin', 'USDC', 1000, Price(1, 1111000)),
        WalletAsset('Algorand', 'ALGO', 2000, Price(0.89, 1000000)),
        WalletAsset('Defly Token', 'DEFLY', 42000, Price(0.0139, 128000))
    ]
