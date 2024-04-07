from flex import db
from flex.blockchain.info import fetch_asset_info
from flex.db.model.blockchain import Asset

session_assets = {}


def get_asset_info(asset_id: int) -> Asset:
    asset = session_assets.get(asset_id)
    if asset is None:
        asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
        if asset is None:
            asset = fetch_asset_info(asset_id)
            db.assets.create(asset)
        session_assets[asset_id] = asset
    return asset
