from dataclasses import dataclass
from datetime import datetime
from unittest.mock import Mock

from dataclasses_json import dataclass_json
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from flex.db.classes.base_entity import BaseEntity
from flex.db.classes.collection_manager import CollectionManager, DbError


@dataclass_json
@dataclass
class ExampleEntity(BaseEntity['ExampleEntity']):
    id: int
    value: str
    created: datetime
    updated: datetime


def _entity(entity_id: int = 42, value: str = 'new') -> ExampleEntity:
    timestamp = datetime(2026, 1, 1)
    return ExampleEntity(
        id=entity_id,
        value=value,
        created=timestamp,
        updated=timestamp,
    )


def test_get_or_create_uses_primary_key_value_and_single_upsert() -> None:
    collection = Mock()
    item = _entity()
    collection.find_one_and_update.return_value = item.to_dict()
    manager = CollectionManager('examples', ExampleEntity, collection)

    result = manager.get_or_create(item)

    assert result == item
    collection.find_one_and_update.assert_called_once_with(
        {'id': 42},
        {'$setOnInsert': item.to_dict()},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    collection.insert_one.assert_not_called()


def test_get_or_create_returns_existing_document_without_overwriting_it() -> None:
    collection = Mock()
    requested = _entity(value='requested')
    existing = _entity(value='existing')
    collection.find_one_and_update.return_value = existing.to_dict()
    manager = CollectionManager('examples', ExampleEntity, collection)

    result = manager.get_or_create(requested)

    assert result == existing


def test_get_or_create_with_delegates_to_upsert_path() -> None:
    collection = Mock()
    item = _entity()
    collection.find_one_and_update.return_value = item.to_dict()
    manager = CollectionManager('examples', ExampleEntity, collection)

    result = manager.get_or_create_with(**item.to_dict())

    assert result == item
    assert collection.find_one_and_update.call_count == 1


def test_get_or_create_recovers_from_concurrent_unique_insert() -> None:
    collection = Mock()
    requested = _entity(value='requested')
    existing = _entity(value='existing')
    collection.find_one_and_update.side_effect = DuplicateKeyError('duplicate id')
    collection.find_one.return_value = existing.to_dict()
    manager = CollectionManager('examples', ExampleEntity, collection)

    result = manager.get_or_create(requested)

    assert result == existing
    collection.find_one.assert_called_once_with({'id': 42})


def test_get_or_create_rejects_missing_upsert_result() -> None:
    collection = Mock()
    collection.find_one_and_update.return_value = None
    manager = CollectionManager('examples', ExampleEntity, collection)

    try:
        manager.get_or_create(_entity())
    except DbError as exc:
        assert exc.code == 500
    else:
        raise AssertionError('Expected DbError for an empty upsert result')
