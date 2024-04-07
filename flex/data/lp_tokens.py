import requests

from flex import db
from flex.data.vestige import BASE_URL
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError


def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{asset1_id}%5D'
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


# def fetch_lp_token_state(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
#     url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{asset1_id}%5D'
#     response = requests.get(url)
#     data = response.json()
#     for token_data in data:
#         if token_data['token_id'] == lp_token_id:
#             price_algo = token_data['price']
#             address = token_data['address']
#             address_balances = get_address_assets(address)
#
#             asset1_reserve = None
#             for asset in address_balances:
#                 if asset.asa_id == asset1_id:
#                     asset1_reserve = asset.amount_micros
#             asset2_reserve = None
#             for asset in address_balances:
#                 if asset.asa_id == asset2_id:
#                     asset2_reserve = asset.amount_micros
#
#             asset1 = get_asset_info(asset1_id)
#             asset2 = get_asset_info(asset2_id)
#
#             return LpToken(
#                 id=lp_token_id,
#                 app_id=token_data['application_id'],
#                 asset1_id=asset1_id,
#                 asset2_id=asset2_id,
#                 dex_provider=dex_provider,
#                 address=address,
#                 asset1_reserve=asset1.micros_to_amount(asset1_reserve),
#                 asset2_reserve=asset2.micros_to_amount(asset2_reserve),
#                 price_usd=price_algo * get_algo_price_usd(),
#                 last_updated_round=get_current_round()
#             )
