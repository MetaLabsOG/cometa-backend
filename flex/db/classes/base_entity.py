import json
from abc import abstractmethod
from datetime import datetime

from typing import Any, TypeVar, Generic

from flex.db.util import string_to_snake_case

EntityT = TypeVar('EntityT')


# IMPLEMENTATIONS MUST be dataclass and dataclass_json
class BaseEntity(Generic[EntityT]):
    @abstractmethod
    def id(self) -> str | int:
        pass

    @abstractmethod
    def updated(self) -> datetime:
        pass

    @abstractmethod
    def created(self) -> datetime:
        pass

    @classmethod
    def primary_key_name(cls) -> str:
        return 'id'

    @property
    def primary_key(self) -> Any:
        return getattr(self, self.primary_key_name())

    @classmethod
    def from_dict(cls, data: dict | None) -> EntityT | None:
        if data is None:
            return None
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return self.to_dict()

    def field(self, name: str, default_factory: callable = None) -> Any:
        res = getattr(self, name)
        if res is None and default_factory is not None:
            res = default_factory()
            setattr(self, name, res)
        return res

    def pretty_str(self) -> str:
        return json.dumps(self.to_dict(), indent=4, default=str)

    @classmethod
    def type_name(cls) -> str:
        return cls.__name__

    @classmethod
    def type_name_snake_case(cls) -> str:
        return string_to_snake_case(cls.type_name())
