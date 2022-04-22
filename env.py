from functools import cached_property

from pydantic import BaseSettings

NODE_MODE = "TESTNET"

# TODO: move all to Settings
MONGO_PORT = 27017
DB_NAME = NODE_MODE

MICROALGOS_IN_ALGO = 1000000

META_ADDRESSES = [
    'METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU',
    'METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM',
    'METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY',
    'METAEVEML4X7TXWHCBP4TKJDUZ7X2O7MSRECM57YA5TPFYSAI6J7WKCX3E', # Custom
    'METAUPN7HLU67ASI4YBYX3BWZEXNYL2CQWGCZES2DM7AGXAHUDZQ2LZMEY'  # Legendary
]


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str

    testnet_algod_address: str
    mainnet_algod_address: str

    algod_token: str

    class Config:
        env_file = '.env'
        arbitrary_types_allowed = True
        keep_untouched = (cached_property,)

    def is_mainnet(self):
        return self.algo_network == 'MAINNET'

    @cached_property
    def algod_address(self):
        return self.mainnet_algod_address if self.is_mainnet() else self.testnet_algod_address


settings = Settings()
