from typing import Type, TypeVar

from pymongo.database import Database as MongoDatabase


EntityT = TypeVar('EntityT')


# HOW TO IMPLEMENT THIS CLASS? Example!
#
# class MetaDatabase(AbstractDatabase):
#     def __init__(self, mongodb_database: Database):
#         super().__init__(mongodb_database)
#         self.players = self.create_collection_manager_for_type(Player)
#
class EntitiesDatabase:
    def __init__(self, mongodb_database: MongoDatabase):
        self.mongodb_database = mongodb_database
        self.collection_manager_by_name = {}

    def get_collection_by_name(self, name: str) -> 'CollectionManager | None':
        return self.collection_manager_by_name.get(name)

    # def create_collection_manager_for_type[EntityT](self, elem_type: Type[EntityT]) -> 'CollectionManager[EntityT]':
    def create_collection_manager_for_type(self, elem_type: Type[EntityT]):
        from core.new.db.classes.collection_manager import CollectionManager
        collection_manager = CollectionManager.create_for_type(elem_type, self.mongodb_database)
        self.collection_manager_by_name[collection_manager.name] = collection_manager
        return collection_manager
