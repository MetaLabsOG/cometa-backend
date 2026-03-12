from dataclasses import dataclass
from typing import Optional

from blockchain.indexer import get_account_assets
from core import tinychart
from core.tinychart import Price
from dexes.tinyman import get_asset_info


@dataclass
class AssetInfo:
    name: str
    ticker: str
    amount: int
    price: Price
    asset_id: int


def get_wallet_assets(address: str) -> list[AssetInfo]:
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


@dataclass
class TimedCost:
    timestamp: int
    cost: Price


@dataclass
class NftInfo:
    asa_id: int
    name: str
    collection: str
    image_url: str
    floor_price: Price
    week_price_change: Optional[float] = None
