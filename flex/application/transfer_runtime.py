"""Composition root for outbound asset transfer infrastructure."""

from functools import lru_cache

from env import settings
from flex import db
from flex.application.asset_transfers import AssetTransferService
from flex.blockchain.asset_transfers import AlgorandAssetTransferGateway
from flex.blockchain.base import algod_client, cometa_private_key, cometa_public_key, indexer_client
from flex.db.asset_transfer_intents import MongoAssetTransferIntentRepository


@lru_cache(maxsize=1)
def get_asset_transfer_service() -> AssetTransferService:
    repository = MongoAssetTransferIntentRepository(
        db.asset_transfer_intents.mongodb_collection,
    )
    repository.ensure_indexes()
    gateway = AlgorandAssetTransferGateway(
        algod=algod_client,
        indexer=indexer_client,
        sender=cometa_public_key,
        private_key=cometa_private_key,
        network=settings.algo_network,
        max_fee_microalgos=settings.outbound_asset_transfer_max_fee_microalgos,
    )
    return AssetTransferService(repository=repository, gateway=gateway)
