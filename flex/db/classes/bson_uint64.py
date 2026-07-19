"""Entity mixin for lossless uint64 selectors and partial updates."""

from typing import Any, ClassVar

from flex.db.bson import encode_uint64_query_value


class BsonUint64StorageMixin:
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def encode_query(
        cls,
        query: dict[str, Any],
    ) -> dict[str, Any]:
        encoded: dict[str, Any] = {}
        for field_name, value in query.items():
            if field_name in cls.BSON_UINT64_FIELDS:
                encoded[field_name] = encode_uint64_query_value(value)
            elif field_name in {"$and", "$nor", "$or"} and isinstance(value, list):
                encoded[field_name] = [
                    cls.encode_query(branch) if isinstance(branch, dict) else branch for branch in value
                ]
            else:
                encoded[field_name] = value
        return encoded

    @classmethod
    def encode_storage_fields(
        cls,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        return cls.encode_query(values)
