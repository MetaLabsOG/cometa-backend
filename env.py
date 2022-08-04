import os
from functools import cached_property

from pydantic import BaseSettings

DIR_PATH = os.path.dirname(os.path.realpath(__file__))


class Settings(BaseSettings):
    algo_network: str

    algo_mnemonic: str
    tinyman_mnemonic: str

    algod_address: str
    algod_token: str

    server_port: int
    mongodb_host: str
    mongodb_port: int

    api_password: str

    algo_price_ttl: int
    asset_prices_ttl: int

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
