import asyncio

import pytest

from flex.meta_error import MetaError
from flex.providers import vestige


class _Response:
    status_code = 200
    text = ""

    def __init__(self, payload: object = None, *, invalid_json: bool = False):
        self._payload = payload
        self._invalid_json = invalid_json

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        if self._invalid_json:
            raise ValueError("invalid JSON")
        return self._payload


class _Client:
    def __init__(self, response: _Response):
        self._response = response

    async def get(self, url: str) -> _Response:
        return self._response


def test_single_price_normalizes_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(
        vestige,
        "_get_client",
        lambda: _Client(_Response(invalid_json=True)),
    )

    with pytest.raises(MetaError, match="Invalid Vestige asset 42/USD JSON"):
        asyncio.run(vestige.get_asset_price_usd_not_cached(42))


def test_full_price_rejects_null_success_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        vestige,
        "_get_client",
        lambda: _Client(_Response([None])),
    )

    with pytest.raises(MetaError, match="response shape"):
        asyncio.run(vestige.vestige_full_asset_price_not_cached(42))
