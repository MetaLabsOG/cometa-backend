from pymongo.database import Database as MongoDatabase

from flex.db.classes.database import EntitiesDatabase
from flex.db.model.airdrop import AirdropManifest
from flex.db.model.blockchain import Asset, LpToken, PoolTransaction, SyncBlock, SyncState
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.model.pool_states import PoolState, UserState
from flex.db.model.pools import FarmingPool, StakingPool
from flex.db.model.priced import AirdropReward, AssetPrice
from flex.db.model.transfers import AssetTransferIntent


class CometaDatabase(EntitiesDatabase):
    def __init__(self, mongodb_database: MongoDatabase):
        super().__init__(mongodb_database)

        self.staking_pools = self.create_collection_manager_for_type(StakingPool)
        self.farming_pools = self.create_collection_manager_for_type(FarmingPool)

        self.assets = self.create_collection_manager_for_type(Asset)
        self.lp_tokens = self.create_collection_manager_for_type(LpToken)

        self.user_states = self.create_collection_manager_for_type(UserState)
        self.pool_states = self.create_collection_manager_for_type(PoolState)
        self.lp_states = self.create_collection_manager_for_type(LpState)

        self.asset_prices = self.create_collection_manager_for_type(AssetPrice)

        self.pool_transactions = self.create_collection_manager_for_type(PoolTransaction)
        self.lp_transactions = self.create_collection_manager_for_type(LpTransaction)

        self.sync_states = self.create_collection_manager_for_type(SyncState)
        self.sync_blocks = self.create_collection_manager_for_type(SyncBlock)

        self.airdrop_rewards = self.create_collection_manager_for_type(AirdropReward)
        self.airdrop_manifests = self.create_collection_manager_for_type(AirdropManifest)
        self.asset_transfer_intents = self.create_collection_manager_for_type(AssetTransferIntent)
