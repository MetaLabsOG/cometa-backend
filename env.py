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

    logging_level: str = 'INFO'
    logging_format: str = '[%(asctime)s][%(levelname)s][%(filename)s] %(message)s'
    logging_date_format: str = '%I:%M:%S'

    return_all_user_pools: bool = False

    background_user_pools_update: bool = False
    background_pools_update: bool = False

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

    contracts_cache_ttl: int = 120
    algo_price_ttl: int = 15
    asset_prices_ttl: int = 30
    lp_token_prices_ttl: int = 60
    total_tvl_ttl: int

    lp_state_ttl_rounds: int = 40  # 2 minutes

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int
    enable_js: bool = True
    reach_no_warn: bool = False
    reach_connector_mode: str = 'ALGO'
    sync_humble_pools: int = 0

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    def is_mainnet(self):
        return self.algo_network == 'mainnet'

    @property
    def db_name(self):
        return self.algo_network.upper()


settings = Settings()

print(f'Algo Network = {settings.algo_network}')
print(f'Mongo URL = {settings.mongodb_host}:{settings.mongodb_port}')
