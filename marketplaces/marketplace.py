from abc import ABC
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Sale:
    asa_id: str
    price: int
    seller: str


@dataclass
class Collection:
    name: str
    addresses: List[str]


class Marketplace(ABC):
    def get_sales(self, creator: str) -> List[Sale]:
        pass

    def get_floor_price(self, creator: str) -> Optional[int]:
        sales = self.get_sales(creator)
        return min((s.price for s in sales), default=None)

    def get_collection_floor_price(self, collection: Collection) -> Optional[int]:
        address_floors = (self.get_floor_price(c) for c in collection.addresses)
        return min(filter(None, address_floors), default=None)
