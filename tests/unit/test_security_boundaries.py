import pytest
from algosdk import encoding
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as app_module
from app import app
from core.auth import require_password
from env import settings


@pytest.mark.asyncio
async def test_api_key_authentication_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "api_password", "")

    with pytest.raises(HTTPException) as exc_info:
        await require_password("")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_api_key_authentication_uses_exact_configured_value(monkeypatch):
    monkeypatch.setattr(settings, "api_password", "configured-test-key")

    await require_password("configured-test-key")

    with pytest.raises(HTTPException) as exc_info:
        await require_password("wrong-test-key")

    assert exc_info.value.status_code == 401


def test_untrusted_host_is_rejected():
    with TestClient(app) as client:
        response = client.get("/status", headers={"host": "attacker.example"})

    assert response.status_code == 400


def test_local_test_host_is_allowed():
    with TestClient(app) as client:
        response = client.get("/status")

    assert response.status_code == 200


def test_wallet_assets_rejects_invalid_address_before_provider_calls():
    with TestClient(app) as client:
        response = client.get("/wallet/not-an-address/assets")

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid Algorand address"}


def test_wallet_assets_limit_is_bounded_by_validation():
    address = encoding.encode_address(bytes(32))

    with TestClient(app) as client:
        response = client.get(f"/wallet/{address}/assets?limit=101")

    assert response.status_code == 422


def test_legacy_migrate_flag_cannot_trigger_startup_mutation(monkeypatch):
    startup_steps: list[str] = []

    monkeypatch.setattr(settings, "migrate", True)
    monkeypatch.setattr(
        app_module,
        "ensure_contract_id_index",
        lambda: startup_steps.append("contract_index"),
    )
    monkeypatch.setattr(
        app_module,
        "ensure_database_indexes",
        lambda database: startup_steps.append("indexes"),
    )
    monkeypatch.setattr(app_module, "get_contracts_by_type", lambda contract_type: [])

    app_module.init_app()

    assert startup_steps == ["contract_index", "indexes"]
