import secrets

from fastapi import Header, HTTPException

from env import settings


async def require_password(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    configured_key = settings.api_password
    if not configured_key or not configured_key.strip():
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if not secrets.compare_digest(configured_key, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
