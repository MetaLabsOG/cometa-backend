from types import SimpleNamespace

import pytest

from dexes import tinyman


def test_init_tinyman_client_has_no_implicit_signer(monkeypatch):
    algod_client = object()
    expected_client = object()
    observed: dict[str, object] = {}

    monkeypatch.setattr(tinyman, "init_algod_client", lambda: algod_client)

    def fake_tinyman_from_algod(algod, address=None):
        observed["algod"] = algod
        observed["address"] = address
        return expected_client

    monkeypatch.setattr(tinyman, "tinyman_from_algod", fake_tinyman_from_algod)

    assert tinyman.init_tinyman_client() is expected_client
    assert observed == {"algod": algod_client, "address": None}


def test_get_pool_info_preserves_requested_asset_order():
    asset1 = SimpleNamespace(id=7, decimals=2)
    asset2 = SimpleNamespace(id=11, decimals=3)
    pool = SimpleNamespace(
        asset_1_reserves=20_000,
        asset_2_reserves=3_000,
        issued_pool_tokens=400,
        asset_1=asset2,
        asset_2=asset1,
        pool_token_asset=SimpleNamespace(name="TMPOOL", decimals=2),
    )

    class FakeClient:
        def fetch_asset(self, asset_id):
            return {7: asset1, 11: asset2}[asset_id]

        def fetch_pool(self, first_asset, second_asset):
            assert (first_asset, second_asset) == (asset1, asset2)
            return pool

    assert tinyman.get_pool_info(FakeClient(), 7, 11) == tinyman.PoolInfo(
        name="TMPOOL",
        asset1_reserve=30.0,
        asset2_reserve=20.0,
        total_lp_tokens=4.0,
    )


def test_asset_registry_rejects_non_object_payload(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b"[]"

    tinyman.get_all_assets.cache_clear()
    monkeypatch.setattr(tinyman.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(ValueError, match="JSON object"):
        tinyman.get_all_assets()
