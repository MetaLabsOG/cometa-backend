import asyncio
import base64
import threading
from types import SimpleNamespace

import httpx
import pytest
from algosdk.logic import get_application_address

from flex.data import lp_tokens
from flex.providers import pact
from flex.providers.vestige import DexProvider

ASSET_A = 31_566_704
ASSET_B = 672_913_181
LP_ID = 885_102_318
APP_ID = 885_102_197


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        invalid_json: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.pact.fi/api/pools")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("upstream failed", request=request, response=response)

    def json(self) -> object:
        if self.invalid_json:
            raise ValueError("invalid JSON")
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, int]]] = []

    async def get(self, url: str, *, params: dict[str, int]) -> _Response:
        self.calls.append((url, params))
        return self.response


def _pool_payload(
    *,
    app_id: object = str(APP_ID),
    primary_id: object = str(ASSET_A),
    secondary_id: object = str(ASSET_B),
    lp_id: object = str(LP_ID),
) -> dict[str, object]:
    return {
        "results": [
            {
                "on_chain_id": app_id,
                "primary_asset": {"on_chain_id": primary_id},
                "secondary_asset": {"on_chain_id": secondary_id},
                "pool_asset": {"on_chain_id": lp_id},
            },
        ],
    }


def _app_info(
    *,
    ltid: object = LP_ID,
    value_type: int = 2,
    config_assets: tuple[int, int] | None = (ASSET_A, ASSET_B),
) -> dict[str, object]:
    global_state: list[dict[str, object]] = []
    if config_assets is not None:
        config = b"".join(value.to_bytes(8, byteorder="big") for value in (*config_assets, 30))
        global_state.append(
            {
                "key": "Q09ORklH",
                "value": {
                    "bytes": base64.b64encode(config).decode(),
                    "type": 1,
                },
            }
        )
    global_state.append(
        {
            "key": "TFRJRA==",
            "value": {"bytes": "", "type": value_type, "uint": ltid},
        }
    )
    return {
        "id": APP_ID,
        "params": {
            "global-state": global_state,
        },
    }


def test_lookup_sorts_assets_and_returns_verified_pool(monkeypatch) -> None:
    client = _Client(_Response(_pool_payload()))
    worker_thread: list[int] = []

    def application_info(app_id: int, *, timeout: int) -> dict[str, object]:
        assert app_id == APP_ID
        assert timeout == 10
        worker_thread.append(threading.get_ident())
        return _app_info()

    monkeypatch.setattr(pact.settings, "algo_network", "mainnet")
    monkeypatch.setattr(pact, "_get_client", lambda: client)
    monkeypatch.setattr(
        pact,
        "algod_client",
        SimpleNamespace(application_info=application_info),
    )
    event_loop_thread = threading.get_ident()

    result = asyncio.run(pact.get_pact_pool_info(ASSET_B, ASSET_A, LP_ID))

    assert result == pact.PactPoolInfo(
        lp_token_id=LP_ID,
        asset1_id=ASSET_B,
        asset2_id=ASSET_A,
        app_id=APP_ID,
        address=get_application_address(APP_ID),
    )
    assert client.calls == [
        (
            "https://api.pact.fi/api/pools",
            {
                "primary_asset__on_chain_id": ASSET_A,
                "secondary_asset__on_chain_id": ASSET_B,
                "limit": 100,
            },
        ),
    ]
    assert worker_thread and worker_thread[0] != event_loop_thread


@pytest.mark.parametrize(
    ("payload", "app_info"),
    [
        (_pool_payload(lp_id=LP_ID + 1), _app_info()),
        (_pool_payload(primary_id=1), _app_info()),
        (_pool_payload(), _app_info(ltid=LP_ID + 1)),
        (_pool_payload(), _app_info(config_assets=(1, 2))),
        (_pool_payload(), _app_info(config_assets=None)),
        (_pool_payload(), _app_info(value_type=1)),
        ({"results": "not-a-list"}, _app_info()),
    ],
)
def test_lookup_fails_closed_on_mismatched_or_malformed_data(
    monkeypatch,
    payload: object,
    app_info: object,
) -> None:
    monkeypatch.setattr(pact.settings, "algo_network", "mainnet")
    monkeypatch.setattr(pact, "_get_client", lambda: _Client(_Response(payload)))
    monkeypatch.setattr(
        pact,
        "algod_client",
        SimpleNamespace(application_info=lambda *_args, **_kwargs: app_info),
    )

    assert asyncio.run(pact.get_pact_pool_info(ASSET_A, ASSET_B, LP_ID)) is None


def test_lookup_returns_none_on_upstream_http_error(monkeypatch) -> None:
    monkeypatch.setattr(pact.settings, "algo_network", "mainnet")
    monkeypatch.setattr(
        pact,
        "_get_client",
        lambda: _Client(_Response({}, status_code=502)),
    )

    assert asyncio.run(pact.get_pact_pool_info(ASSET_A, ASSET_B, LP_ID)) is None


def test_lookup_returns_none_on_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(pact.settings, "algo_network", "mainnet")
    monkeypatch.setattr(
        pact,
        "_get_client",
        lambda: _Client(_Response(None, invalid_json=True)),
    )

    assert asyncio.run(pact.get_pact_pool_info(ASSET_A, ASSET_B, LP_ID)) is None


def test_lp_lookup_falls_back_to_vestige_when_pact_is_unavailable(monkeypatch) -> None:
    expected = object()
    calls: list[tuple[int, int, int, str]] = []

    async def no_pact_pool(*_args: object) -> None:
        return None

    async def vestige_pool(
        lp_token_id: int,
        asset1_id: int,
        asset2_id: int,
        dex_provider: str,
    ) -> object:
        calls.append((lp_token_id, asset1_id, asset2_id, dex_provider))
        return expected

    monkeypatch.setattr(lp_tokens, "get_pact_pool_info", no_pact_pool)
    monkeypatch.setattr(lp_tokens.vestige, "fetch_lp_token", vestige_pool)

    result = asyncio.run(
        lp_tokens.fetch_lp_token_strong(
            LP_ID,
            ASSET_A,
            ASSET_B,
            DexProvider.PACT,
        ),
    )

    assert result is expected
    assert calls == [(LP_ID, ASSET_A, ASSET_B, DexProvider.PACT)]


@pytest.mark.parametrize(
    "ids",
    [
        (-1, ASSET_B, LP_ID),
        (ASSET_A, True, LP_ID),
        (ASSET_A, ASSET_B, 0),
        ("31566704", ASSET_B, LP_ID),
        (ASSET_A, ASSET_B, 1 << 64),
    ],
)
def test_lookup_rejects_invalid_ids(ids: tuple[object, object, object]) -> None:
    with pytest.raises(pact.PactPayloadError):
        asyncio.run(pact.get_pact_pool_info(*ids))


def test_lookup_rejects_unsupported_network(monkeypatch) -> None:
    monkeypatch.setattr(pact.settings, "algo_network", "dev")

    with pytest.raises(ValueError, match="Unsupported Pact network"):
        asyncio.run(pact.get_pact_pool_info(ASSET_A, ASSET_B, LP_ID))
