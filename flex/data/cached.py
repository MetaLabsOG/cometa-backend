from flex import db
from flex.blockchain.info import fetch_asset_info
from flex.data.lp_tokens import fetch_lp_token, fetch_lp_token_by_id
from flex.db.model.blockchain import Asset, LpToken

session_assets = {}
session_lp_tokens = {}


def get_asset_info(asset_id: int) -> Asset:
    asset = session_assets.get(asset_id)
    if asset is None:
        asset = db.assets.get_by_primary_key(asset_id, throw_ex=False)
        if asset is None:
            asset = fetch_asset_info(asset_id)
            db.assets.create(asset)
        session_assets[asset_id] = asset
    return asset


def get_lp_token_info(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    lp_token = session_lp_tokens.get(lp_token_id)
    if lp_token is None:
        lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
        if lp_token is None:
            lp_token = fetch_lp_token(lp_token_id, asset1_id, asset2_id, dex_provider)
            db.lp_tokens.create(lp_token)
        session_lp_tokens[lp_token_id] = lp_token
    return lp_token


def get_lp_token_info_by_id(lp_token_id: int) -> LpToken:
    lp_token = session_lp_tokens.get(lp_token_id)
    if lp_token is None:
        lp_token = db.lp_tokens.get_by_primary_key(lp_token_id, throw_ex=False)
        if lp_token is None:
            lp_token = fetch_lp_token_by_id(lp_token_id)
            db.lp_tokens.create(lp_token)
        session_lp_tokens[lp_token_id] = lp_token
    return lp_token
