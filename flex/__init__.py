"""Flex domain package with lazy infrastructure initialization."""

from importlib import import_module
from threading import Lock
from typing import Any

# Load the namespace package once so later ``flex.db.*`` imports do not replace
# the public ``db`` dependency below on the parent package.
import_module(f"{__name__}.db")


class _LazyCometaDatabase:
    """Initialize MongoDB only when a domain operation first needs it."""

    def __init__(self) -> None:
        self._instance: Any | None = None
        self._client: Any | None = None
        self._lock = Lock()

    def _load(self) -> Any:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    from pymongo import MongoClient

                    from env import settings
                    from flex.db.cometa_database import CometaDatabase

                    client = MongoClient(
                        host=settings.mongodb_host,
                        port=settings.mongodb_port,
                        username=settings.mongodb_username,
                        password=settings.mongodb_password,
                    )
                    self._client = client
                    self._instance = CometaDatabase(client[settings.new_db_name])
        return self._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


db = _LazyCometaDatabase()
