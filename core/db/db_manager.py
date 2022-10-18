from dataclasses import dataclass
from functools import cached_property
from typing import TypeVar, Generic, Any

from core.db.mongodb import get_db_collection

T = TypeVar('T')


@dataclass
class DbManager(Generic[T]):
    db_name: str
    name: str
    primary_key: str
    type: Any

    @cached_property
    def collection(self):
        return get_db_collection(self.db_name, self.name)

    def create(self, item: T) -> T:
        self.collection.insert_one(item.to_dict())
        return item

    def get_one(self, args: dict) -> T:
        item = self.collection.find_one(args)
        return self.type.from_dict(item) if item is not None else None

    def get_by_primary_key(self, val: Any) -> T:
        return self.get_one({self.primary_key: val})

    def get_many(self, args: dict) -> list[T]:
        items = self.collection.find(args)
        return [self.type.from_dict(i) for i in items]

    def get_all(self) -> list[T]:
        return self.get_many({})

    def update(self, item: T) -> T:
        item_dict = item.to_dict()
        if self.db_name == 'COMETA_BOT':
            print(f'UPDATING DB: \n{self.primary_key}:{item_dict.get(self.primary_key)}\nSetting to {item_dict}')
        self.collection.update_one({self.primary_key: item_dict.get(self.primary_key)}, {'$set': item_dict})
        return item

    def remove(self, args: dict) -> int:
        res = self.collection.delete_many(args)
        return res.deleted_count
