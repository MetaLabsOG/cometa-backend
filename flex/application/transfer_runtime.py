"""Composition root for outbound asset transfer infrastructure."""

from functools import lru_cache

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
    )
    return AssetTransferService(repository=repository, gateway=gateway)
