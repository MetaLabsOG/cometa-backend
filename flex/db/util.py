import re
import uuid
from typing import Any


def string_to_snake_case(s: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()


def get_uuid() -> str:
    return str(uuid.uuid4())


def dict_get_nested_field(data: dict, *field_names: str) -> Any:
    for field_name in field_names:
        if field_name not in data:
            return None
        data = data[field_name]
    return data


def dict_set_nested_field_and_create(data: dict, value: Any, *field_names: str) -> Any:
    for field_name in field_names[:-1]:
        if field_name not in data:
            data[field_name] = {}
        data = data[field_name]
    data[field_names[-1]] = value


def dict_set_nested_field(data: dict, value: Any, *field_names: str) -> Any:
    for field_name in field_names[:-1]:
        if field_name not in data:
            return None
        data = data[field_name]
    data[field_names[-1]] = value
