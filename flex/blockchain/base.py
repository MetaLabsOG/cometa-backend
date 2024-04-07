from datetime import timedelta

from algosdk import mnemonic, account
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient

from env import settings

BLOCKS_IN_A_YEAR = int(timedelta(days=365).total_seconds() / settings.block_time)


indexer_client: IndexerClient = IndexerClient(
    indexer_token=settings.algod_token,
    indexer_address=settings.algo_indexer_address
)
algod_client: AlgodClient = AlgodClient(
    settings.algod_token,
    settings.algod_address,
    headers={
        'User-Agent': 'py-algorand-sdk',
        'X-API-Key': settings.algod_token
    }
)

cometa_private_key = mnemonic.to_private_key(settings.algo_mnemonic)
cometa_public_key = account.address_from_private_key(cometa_private_key)
