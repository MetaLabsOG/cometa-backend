from pymongo.database import Database as MongoDatabase

from core.new.db.classes.database import EntitiesDatabase
from core.new.db.model import UserState, PoolState, PoolTransaction


class CometaDatabase(EntitiesDatabase):
    def __init__(self, mongodb_database: MongoDatabase):
        super().__init__(mongodb_database)

        self.user_states = self.create_collection_manager_for_type(UserState)
        self.pool_states = self.create_collection_manager_for_type(PoolState)
        self.pool_transactions = self.create_collection_manager_for_type(PoolTransaction)
