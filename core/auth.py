import secrets

from fastapi import Header, HTTPException

from env import settings


async def require_password(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    if not secrets.compare_digest(settings.api_password, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
