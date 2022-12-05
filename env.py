from functools import cached_property

from pydantic import BaseSettings


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int

    algod_address: str
    algod_token: str

    algo_indexer_address: str

    server_port: int
    workers_num: int

    mongodb_host: str
    mongodb_port: int
    migrate: bool = False

    api_password: str
    logging_level: str = 'INFO'

    block_time: float = 3.7

    algo_price_ttl: int
    asset_prices_ttl: int
    total_tvl_ttl: int

    contracts_cache_ttl: int = 300

    class Config:
        env_file = '.env'
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)

    def is_mainnet(self):
        return self.algo_network == 'mainnet'

    @property
    def db_name(self):
        return self.algo_network.upper()


settings = Settings()

print(f'Algo Network = {settings.algo_network}')
print(f'Mongo URL = {settings.mongodb_host}:{settings.mongodb_port}')
