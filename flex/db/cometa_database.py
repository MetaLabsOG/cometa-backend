from pymongo.database import Database as MongoDatabase

from flex.db.classes.database import EntitiesDatabase
from flex.db.model import UserState, PoolState, PoolTransaction, StakingPool, FarmingPool, LPToken


class CometaDatabase(EntitiesDatabase):
    def __init__(self, mongodb_database: MongoDatabase):
        super().__init__(mongodb_database)

        self.staking_pools = self.create_collection_manager_for_type(StakingPool)
        self.farming_pools = self.create_collection_manager_for_type(FarmingPool)
        self.user_states = self.create_collection_manager_for_type(UserState)
        self.pool_states = self.create_collection_manager_for_type(PoolState)
        self.pool_transactions = self.create_collection_manager_for_type(PoolTransaction)
        self.lp_tokens = self.create_collection_manager_for_type(LPToken)
