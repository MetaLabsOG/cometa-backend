from functools import cached_property

from pydantic import BaseSettings

MICROALGOS_IN_ALGO = 1000000

META_TOTAL_SUPPLY = 10000000
META_DECIMALS = 6

TESTNET_META_ASA_ID = 85401361
MAINNET_META_ASA_ID = 712012773


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str

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

    @cached_property
    def meta_asa_id(self):
        return MAINNET_META_ASA_ID if self.is_mainnet() else TESTNET_META_ASA_ID

    @property
    def db_name(self):
        return self.algo_network


settings = Settings()
