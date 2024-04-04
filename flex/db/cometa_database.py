from pymongo.database import Database as MongoDatabase

from flex.db.classes.database import EntitiesDatabase
from flex.db.model.blockchain import LpToken, Asset, PoolTransaction, SyncState, SyncBlock
from flex.db.model.pool_states import UserState, PoolState
from flex.db.model.pools import StakingPool, FarmingPool
from flex.db.model.priced import AirdropReward


class CometaDatabase(EntitiesDatabase):
    def __init__(self, mongodb_database: MongoDatabase):
        super().__init__(mongodb_database)

        self.staking_pools = self.create_collection_manager_for_type(StakingPool)
        self.farming_pools = self.create_collection_manager_for_type(FarmingPool)
        self.user_states = self.create_collection_manager_for_type(UserState)
        self.pool_states = self.create_collection_manager_for_type(PoolState)
        self.pool_transactions = self.create_collection_manager_for_type(PoolTransaction)

        self.assets = self.create_collection_manager_for_type(Asset)
        self.lp_tokens = self.create_collection_manager_for_type(LpToken)

        self.airdrop_rewards = self.create_collection_manager_for_type(AirdropReward)

        self.sync_states = self.create_collection_manager_for_type(SyncState)
        self.sync_blocks = self.create_collection_manager_for_type(SyncBlock)
