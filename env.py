from functools import cached_property

from pydantic import BaseSettings

MICROALGOS_IN_ALGO = 1000000

DEFAULT_CLIENT_ADDRESS = 'YGXBCM7TE2UUVL6OAYBJU2QN25NH5OQLXTNMK4ZD5NG45QOHH6YD4WK3OA'


class Settings(BaseSettings):
    algo_network: str

    algo_mnemonic: str
    tinyman_mnemonic: str

    testnet_algod_address: str
    mainnet_algod_address: str

    algod_token: str

    mongodb_port: int

    class Config:
        env_file = '.env'
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)

    def is_mainnet(self):
        return self.algo_network == 'MAINNET'

    @cached_property
    def algod_address(self):
        return self.mainnet_algod_address if self.is_mainnet() else self.testnet_algod_address

    @property
    def db_name(self):
        return self.algo_network


settings = Settings()
