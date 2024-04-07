import requests

from flex.blockchain.info import get_address_assets, get_current_round
from flex.data.cached import get_asset_info
from flex.data.vestige import BASE_URL, get_algo_price_usd
from flex.db.model.blockchain import LpToken


def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{asset1_id}%5D'
    response = requests.get(url)
    data = response.json()
    for token_data in data:
        if token_data['token_id'] == lp_token_id:
            price_algo = token_data['price']
            address = token_data['address']
            address_balances = get_address_assets(address)

            asset1_reserve = None
            for asset in address_balances:
                if asset.asa_id == asset1_id:
                    asset1_reserve = asset.amount_micros
            asset2_reserve = None
            for asset in address_balances:
                if asset.asa_id == asset2_id:
                    asset2_reserve = asset.amount_micros

            asset1 = get_asset_info(asset1_id)
            asset2 = get_asset_info(asset2_id)

            return LpToken(
                id=lp_token_id,
                app_id=token_data['application_id'],
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex_provider=dex_provider,
                address=address,
                asset1_reserve=asset1.micros_to_amount(asset1_reserve),
                asset2_reserve=asset2.micros_to_amount(asset2_reserve),
                price_usd=price_algo * get_algo_price_usd(),
                last_updated_round=get_current_round()
            )
