from dataclasses import dataclass
from threading import Condition
from typing import Optional

from cachetools import TTLCache, cached

from blockchain.indexer import get_account_assets
from core import tinychart
from core.tinychart import Price
from dexes.tinyman import get_asset_info

MAX_WALLET_ASSETS = 100
_wallet_assets_cache = TTLCache(maxsize=256, ttl=30)
_wallet_assets_cache_condition = Condition()


@dataclass
class AssetInfo:
    name: str
    ticker: str
    amount: int
    price: Price
    asset_id: int


@cached(cache=_wallet_assets_cache, condition=_wallet_assets_cache_condition)
def get_wallet_assets(address: str) -> list[AssetInfo]:
    wallet_assets = get_account_assets(address)
    eligible_assets = [asset for asset in wallet_assets if asset["amount"] and not asset["deleted"]]
    eligible_assets.sort(key=lambda asset: asset["asset-id"] != 0)

    res = []
    for asset in eligible_assets[:MAX_WALLET_ASSETS]:
        asset_id = asset["asset-id"]
        asset_info = get_asset_info(asset_id)
        if asset_info is not None:
            asset_amount = asset["amount"] / 10 ** asset_info["decimals"]
            asset_price = tinychart.get_asset_price_full(asset_id)
            res.append(AssetInfo(asset_info["name"], asset_info["unit_name"], asset_amount, asset_price, asset_id))

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
