from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str

    cometa_algo_mnemonic: str
    cometa_rekey_mnemonic: str

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int

    algod_address: str
    algod_token: str

    algo_indexer_address: str

    server_port: int
    workers_num: int

    mongodb_host: str
    mongodb_port: int

    rekeyed_mnemonic: str = None
    migrate: bool = False

    api_password: str
    logging_level: str = 'INFO'

    block_time: float = 3.3

    contracts_cache_ttl: int = 120
    algo_price_ttl: int
    asset_prices_ttl: int
    total_tvl_ttl: int

    lottery_check_lock: bool = True


    background_user_pools_update: bool = True

    telegram_bot_api_token: str
    telegram_channel_id: int

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    reach_no_warn: bool = False
    reach_connector_mode: str = 'ALGO'
    sync_humble_pools: int = 0

    def is_mainnet(self):
        return self.algo_network == 'mainnet'

    @property
    def db_name(self):
        return self.algo_network.upper()


settings = Settings()

print(f'Algo Network = {settings.algo_network}')
print(f'Mongo URL = {settings.mongodb_host}:{settings.mongodb_port}')

print(f'All settings: {settings.dict()}')
