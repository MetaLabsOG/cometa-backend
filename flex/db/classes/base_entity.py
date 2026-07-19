import json
from datetime import datetime
from typing import Any, Generic, TypeVar

from flex.db.util import string_to_snake_case

EntityT = TypeVar("EntityT")


# IMPLEMENTATIONS MUST be dataclass and dataclass_json
class BaseEntity(Generic[EntityT]):
    id: int | str
    updated: datetime
    created: datetime

    @classmethod
    def primary_key_name(cls) -> str:
        return "id"

    @classmethod
    def encode_query(cls, query: dict[str, Any]) -> dict[str, Any]:
        """Encode entity-specific storage types used in Mongo selectors."""
        return dict(query)

    @classmethod
    def encode_storage_fields(
        cls,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """Encode a partial Mongo update using the entity storage schema."""
        return dict(values)

    @property
    def primary_key(self) -> Any:
        return getattr(self, self.primary_key_name())

    @classmethod
    def from_dict(cls, data: dict | None) -> EntityT | None:
        if data is None:
            return None
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return self.__class__.to_dict(self)

    def field(self, name: str, default_value: Any = None, default_factory: callable = None) -> Any:
        res = getattr(self, name)
        if res is None:
            if default_value is not None:
                res = default_value
            elif default_factory is not None:
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
