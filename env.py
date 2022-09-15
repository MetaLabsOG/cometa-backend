import os
from functools import cached_property

from pydantic import BaseSettings

DIR_PATH = os.path.dirname(os.path.realpath(__file__))

LOG_FORMAT = '[%(asctime)s][%(levelname)s][%(filename)s] %(message)s'
DATE_FORMAT = '%I:%M:%S'


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int

    algod_address: str
    algod_token: str

    server_port: int
    workers_num: int

    mongodb_host: str
    mongodb_port: int

    api_password: str
    logging_level: str = 'INFO'

    block_time: float = 4.35

    algo_price_ttl: int
    asset_prices_ttl: int
    total_tvl_ttl: int

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
