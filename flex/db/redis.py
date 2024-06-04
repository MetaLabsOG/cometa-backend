import logging
from typing import Callable, Any

from env import settings

from aiocache import Cache


logger = logging.getLogger(__name__)

# cache = Cache(Cache.REDIS, endpoint=settings.redis_host, port=settings.redis_port, namespace="main")
#
#
# async def global_cache_get(key: str, cls, fetch_func: Callable[[], Any], ttl: int = 120) -> Any:
#     cached_data = await cache.get(key)
#     if cached_data:
#         return cls.from_dict(cached_data) if isinstance(cached_data, dict) else cached_data
#
#     data = await fetch_func()
#     if data:
#         await cache.set(key, data.to_dict() if hasattr(data, 'to_dict') else data, ttl=ttl)  # Cache the data
#     return data