import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str
    rekeyed_mnemonic: str = None

    algod_address: str
    algod_token: str
    algo_indexer_address: str

    server_port: int
    workers_num: int
    api_password: str
    migrate: bool = False

    mongodb_host: str
    mongodb_port: int
    new_db_name: str = 'cometa-updated'

    redis_host: str
    redis_port: int

    logging_level: str = 'INFO'
    logging_format: str = '[%(asctime)s][%(levelname)s][%(filename)s] %(message)s'
    logging_date_format: str = '%I:%M:%S'

    return_all_user_pools: bool = False
    # TODO: remove HARDCORE
    always_return_pool_ids: list[int] = [1705298492, 1713659453, 1846754940, 1911323813, 1911383471]
    return_all_cometa_pools_to_addresses: list[str] = []

    background_user_pools_update: bool = False
    background_pools_update: bool = False
    background_asset_prices_update: bool = True  # Enable background update of asset prices
    asset_price_update_batch_size: int = 10  # Number of assets to update in one batch
    asset_price_api_call_delay: float = 0.5  # Delay between API calls in seconds
    asset_price_batch_delay: float = 2.0  # Delay between batches in seconds

    sync_new_pools: bool = True
    sync_liquidity_pools: bool = False
    update_contract_caches: bool = True
    update_contracts_chunk_size: int = 10

    telegram_bot_api_token: str
    telegram_channel_id: int
    discord_notify_webhook_url: Optional[str] = None

    block_time: float = 2.7
    old_pool_end_date_days_ago: int = 30
    sync_lag_max_rounds: int = 1000  # 1 hour
    sync_behind_seconds_threshold: int = 60

    reset_and_resync_pool_states: bool = False

    contracts_cache_ttl: int = 30
    algo_price_ttl: int = 3
    asset_prices_ttl: int = 30
    asset_prices_update_interval: int = 60  # Run the background update every 60 seconds
    lp_token_prices_ttl: int = 30
    total_tvl_ttl: int = 30

    lp_state_ttl_rounds: int = 10  # 30s

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int
    enable_js: bool = True
    reach_no_warn: bool = False
    reach_connector_mode: str = 'ALGO'
    sync_humble_pools: int = 0

    asset_default_logo_svg_url: str = 'https://app.cometa.farm/static/media/tokenPlaceholder.b822bbf7d312b67292cf97f3d22194ed.svg'

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    def is_mainnet(self):
        return self.algo_network == 'mainnet'

    @property
    def db_name(self):
        return self.algo_network.upper()


settings = Settings()

DIR_PATH = os.path.dirname(os.path.realpath(__file__))


print(f'Algo Network = {settings.algo_network}')
print(f'Mongo URL = {settings.mongodb_host}:{settings.mongodb_port}')
print(f'Alway Return Pool IDs = {settings.always_return_pool_ids}')
print(f'Return All Cometa Pools to Addresses = {settings.return_all_cometa_pools_to_addresses}')
