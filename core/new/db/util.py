import re
import uuid


def string_to_snake_case(s: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()


def get_uuid() -> str:
    return str(uuid.uuid4())
