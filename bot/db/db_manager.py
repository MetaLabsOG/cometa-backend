from dataclasses import dataclass
from functools import cached_property
from typing import TypeVar, Generic

from bot.db.mongo import get_collection

T = TypeVar('T')


@dataclass
class DbManager(Generic[T]):
    name: str
    primary_key: str

    @cached_property
    def collection(self):
        return get_collection(self.name)

    def create(self, item: T) -> T:
        self.collection.insert_one(item.to_dict())
        return item

    def get_one(self, args: dict) -> T:
        item = self.collection.find_one(args)
        return T.from_dict(item) if item is not None else None

    def get_many(self, args: dict) -> list[T]:
        items = self.collection.find(args)
        return [T.from_dict(i) for i in items]

    def update(self, item: T) -> T:
        item_dict = item.to_dict()
        self.collection.update_one({self.primary_key: item_dict.get(self.primary_key)}, {'$set': item_dict})
        return item
