import typing
from abc import ABC
from dataclasses import dataclass


@dataclass
class Sale:
    asa_id: str
    price: int
    seller: str


# TODO: refactor implementations with this
class Marketplace(ABC):
    def get_sales(self, creator: str) -> typing.List[Sale]:
        pass

    def get_floor_price(self, creator: str) -> int:
        sales = self.get_sales(creator)
        return min(s.price for s in sales)

    def get_collection_floor_price(self, creators: typing.List[str]) -> int:
        return min(self.get_floor_price(c) for c in creators)
