import os
from functools import cached_property

from pydantic import BaseSettings

ENVIRONMENT = os.getenv('COMETA_ENVIRONMENT', default='test')


class Settings(BaseSettings):
    algo_network: str

    algo_mnemonic: str
    tinyman_mnemonic: str

    algod_address: str
    algod_token: str

    mongodb_port: int

    class Config:
        env_file = f'.env.{ENVIRONMENT}'
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)

    def is_mainnet(self):
        return self.algo_network == 'MAINNET'

    @property
    def db_name(self):
        return self.algo_network


settings = Settings()
