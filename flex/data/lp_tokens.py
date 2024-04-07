import requests

from flex import db
from flex.data.vestige import BASE_URL
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError


def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    ref_id = asset2_id if asset1_id == 0 else asset1_id
    url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{ref_id}%5D'
    response = requests.get(url)
    data = response.json()
    for token_data in data:
        if token_data['token_id'] == lp_token_id:
            address = token_data['address']
            return LpToken(
                id=lp_token_id,
                pool_id=token_data['id'],
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex_provider=dex_provider,
                address=address,
            )


def fetch_lp_token_by_id(lp_token_id: int) -> LpToken:
    farming_pool = db.farming_pools.get_one(**{'stake_token.id': lp_token_id})
    if farming_pool is None:
        raise MetaError(f'Farming pool with stake asset id {lp_token_id} not found')
    return fetch_lp_token(
        lp_token_id=lp_token_id,
        asset1_id=farming_pool.first_token.id,
        asset2_id=farming_pool.second_token.id,
        dex_provider=farming_pool.dex_name
    )


session_lp_tokens = {}


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
