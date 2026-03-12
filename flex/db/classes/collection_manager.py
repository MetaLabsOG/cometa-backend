from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

from pymongo import DESCENDING, ASCENDING
from pymongo.collection import Collection as MongoCollection
from typing import TypeVar, Generic, Any, Type

from pymongo.database import Database as MongoDatabase


@dataclass
class DbError(Exception):
    code: int
    message: str


EntityT = TypeVar('EntityT', bound='BaseEntity')


@dataclass
class CollectionManager(Generic[EntityT]):
    name: str
    elem_type: Type[EntityT]
    mongodb_collection: MongoCollection

    def create(self, item: EntityT) -> EntityT:
        self.mongodb_collection.insert_one(item.to_dict())
        return item

    def create_many(self, items: list[EntityT]) -> list[EntityT]:
        item_dicts = [i.to_dict() for i in items]
        self.mongodb_collection.insert_many(item_dicts)
        return items

    def create_with(self, **kwargs) -> EntityT:
        item = self.elem_type(**kwargs)
        return self.create(item)

    def get_one(self, **kwargs) -> EntityT | None:
        res = self.mongodb_collection.find_one(kwargs)
        if res is None:
            return None
        return self.item_from_dict(dict(res))

    def get_by_primary_key(self, val: Any, throw_ex: bool = True) -> EntityT | None:
        res = self.get_one(**{self.primary_key_name: val})
        if res is None and throw_ex:
            raise DbError(code=404, message=f'No {self.name} found with {self.primary_key_name}={val}')
        return res

    def get_or_create(self, item: EntityT) -> EntityT:
        res = self.get_by_primary_key(self.primary_key_name, throw_ex=False)
        if res is None:
            res = self.create(item)
        return res

    def get_or_create_with(self, **kwargs) -> EntityT:
        res = self.get_by_primary_key(kwargs.get(self.primary_key_name), throw_ex=False)
        if res is None:
            res = self.create_with(**kwargs)
        return res

    def get_many(self, **kwargs) -> list[EntityT]:
        items = self.mongodb_collection.find(kwargs)
        return [self.item_from_dict(i) for i in items]

    def get_many_by_query(
            self,
            query_dict: dict,
            sort_by: str | None = None,
            reversed: bool = False,
            limit: int| None = None
    ) -> list[EntityT]:
        items = self.mongodb_collection.find(query_dict)
        if sort_by is not None:
            items = items.sort(sort_by, DESCENDING if reversed else ASCENDING)
        elif reversed:
            items = items.sort('_id', DESCENDING)
        if limit is not None:
            items = items.limit(limit)
        return [self.item_from_dict(i) for i in items]

    def get_by_array(self, field_name: str, values: list[Any]) -> list[EntityT]:
        return self.get_many(**{field_name: {'$in': values}})

    def get_all(self) -> list[EntityT]:
        return self.get_many()

    def update(self, item: EntityT) -> EntityT:
        item.updated = datetime.now()
        item_dict = item.to_dict()
        self.mongodb_collection.update_one(
            {self.primary_key_name: item.primary_key}, {'$set': item_dict}
        )
        return item

    def update_with(self, item: EntityT, **kwargs) -> EntityT:
        kwargs['updated'] = datetime.now()
        self.mongodb_collection.update_one(
            {self.primary_key_name: item.primary_key}, {'$set': kwargs}
        )
        item_dict = item.to_dict()
        item_dict.update(kwargs)
        return self.item_from_dict(item_dict)

    def update_many_with(self, filter: dict, **kwargs) -> int:
        kwargs['updated'] = datetime.now()
        res = self.mongodb_collection.update_many(filter, {'$set': kwargs})
        return res.modified_count

    def remove(self, item: EntityT) -> bool:
        res = self.mongodb_collection.delete_one(
            {self.primary_key_name: item.primary_key}
        )
        return res.deleted_count > 0

    def remove_by(self, **kwargs) -> int:
        res = self.mongodb_collection.delete_many(kwargs)
        return res.deleted_count

    def remove_all(self) -> int:
        return self.remove_by()

    def count(self, **kwargs) -> int:
        return self.mongodb_collection.count_documents(kwargs)

    def exists(self, **kwargs) -> bool:
        return self.mongodb_collection.find_one(kwargs, projection={'_id': 1}) is not None

    def item_from_dict(self, item_dict: dict) -> EntityT:
        return self.elem_type.from_dict(item_dict)

    @cached_property
    def primary_key_name(self) -> str:
        return self.elem_type.primary_key_name()

    @classmethod
    def create_for_type(cls, elem_type: Type[EntityT], mongodb_database: MongoDatabase) -> 'CollectionManager[EntityT]':
        name = f'{elem_type.type_name_snake_case()}s'
        collection = mongodb_database[name]
        return cls(name, elem_type, collection)
