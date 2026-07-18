import logging
from types import SimpleNamespace
from typing import Any

import pytest
from algosdk import encoding
from fastapi import HTTPException
from pydantic import ValidationError

import app as api_module
from api import background
from api.db_model import ContractType
from env import Settings
from flex.blockchain import contract_state
from flex.blockchain.contract_state import (
    ContractStateDecodeError,
    ContractStateFetchError,
)


def _view(beneficiary: str) -> dict[str, dict[str, Any]]:
    return {
        "initial": {
            "beneficiary": beneficiary,
            "beginBlock": {"type": "BigNumber", "hex": "0x01"},
            "endBlock": {"type": "BigNumber", "hex": "0x02"},
            "lockLengthBlocks": {"type": "BigNumber", "hex": "0x00"},
        },
        "global": {"totalStaked": {"type": "BigNumber", "hex": "0x00"}},
    }


@pytest.mark.parametrize("chunk_size", [0, 101])
def test_settings_reject_invalid_contract_refresh_chunk_size(chunk_size: int) -> None:
    with pytest.raises(ValidationError):
        Settings(update_contracts_chunk_size=chunk_size)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "farm", "id": True, "version": "17.2.5"},
        {"type": "farm", "id": 0, "version": "17.2.5"},
        {"type": "farm", "id": -1, "version": "17.2.5"},
        {"type": "farm", "id": 1, "version": ""},
        {"type": "farm", "id": 1, "version": "17.0.5"},
        {"type": "distribution", "id": 1, "version": "17.2.5"},
    ],
)
def test_registration_model_rejects_invalid_identity(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        api_module.AddContract.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "status_code"),
    [
        (ContractStateDecodeError("layout mismatch"), 409),
        (ContractStateFetchError("provider unavailable"), 503),
        (RuntimeError("unexpected"), 500),
    ],
)
async def test_contract_view_maps_failures_to_stable_http_statuses(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status_code: int,
) -> None:
    async def fail_fetch(*_args: object) -> None:
        raise failure

    monkeypatch.setattr(api_module, "fetch_contract_views", fail_fetch)

    with pytest.raises(HTTPException) as error:
        await api_module._fetch_contract_view(42, "farm", "^17.2.5")

    assert error.value.status_code == status_code


@pytest.mark.asyncio
async def test_registration_preserves_metadata_and_native_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beneficiary = f"0x{encoding.decode_address(api_module.settings.beneficiary_address).hex()}"
    view = _view(beneficiary)
    captured: dict[str, Any] = {}

    async def fetch_view(*_args: object) -> dict[str, dict[str, Any]]:
        return view

    async def create_contract(contract: object, metadata: dict[str, Any]) -> SimpleNamespace:
        captured["contract"] = contract
        captured["metadata"] = metadata
        return SimpleNamespace(
            metadata={
                "begin_block": 1,
                "end_block": 2,
                "lock_length_blocks": 0,
            }
        )

    async def notify_new_pool(**kwargs: object) -> None:
        captured["notification"] = kwargs

    monkeypatch.setattr(api_module, "get_contract", lambda _app_id: None)
    monkeypatch.setattr(api_module, "_fetch_contract_view", fetch_view)
    monkeypatch.setattr(api_module, "create_contract", create_contract)
    monkeypatch.setattr(api_module, "notify_new_pool", notify_new_pool)

    contract = api_module.AddContract(
        type=ContractType.FARM,
        id=42,
        version="^17.2.5",
        metadata={"source": "test"},
    )

    await api_module.register_contract(contract)

    assert captured["metadata"] == {"source": "test", "cache": view}
    assert captured["notification"]["metadata"] == {"source": "test"}


@pytest.mark.asyncio
async def test_registration_rejects_wrong_beneficiary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_view(*_args: object) -> dict[str, dict[str, Any]]:
        return _view(f"0x{bytes(32).hex()}")

    monkeypatch.setattr(api_module, "get_contract", lambda _app_id: None)
    monkeypatch.setattr(api_module, "_fetch_contract_view", fetch_view)

    with pytest.raises(HTTPException) as error:
        await api_module.register_contract(
            api_module.AddContract(
                type=ContractType.FARM,
                id=42,
                version="17.2.5",
            )
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_manual_refresh_reports_partial_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = [
        SimpleNamespace(id=1, type="farm", version="^17.2.5", metadata={"keep": True}),
        SimpleNamespace(id=2, type="farm", version="^17.2.5", metadata={}),
    ]
    view = _view(f"0x{bytes(32).hex()}")
    updates: list[tuple[int, dict[str, Any]]] = []
    invalidations = 0

    async def fetch_batch(
        rows: list[dict[str, Any]],
        contract_type: str,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        assert [row["id"] for row in rows] == [1, 2]
        assert contract_type == "farm"
        return {"1": view}

    def invalidate() -> None:
        nonlocal invalidations
        invalidations += 1

    monkeypatch.setattr(api_module, "get_contracts_by_type", lambda _type: contracts)
    monkeypatch.setattr(contract_state, "fetch_contracts_views_batch", fetch_batch)
    monkeypatch.setattr(
        api_module,
        "update_contract",
        lambda app_id, *, metadata: updates.append((app_id, metadata)),
    )
    monkeypatch.setattr(api_module, "invalidate_contracts_cache", invalidate)

    result = await api_module.refresh_contracts_cache(type=ContractType.FARM)

    assert result == {"refreshed": 1, "errors": 1}
    assert updates == [(1, {"keep": True, "cache": view})]
    assert invalidations == 1


@pytest.mark.asyncio
async def test_background_refresh_logs_actual_partial_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contracts = [
        SimpleNamespace(id=1, version="^17.2.5", metadata=None),
        SimpleNamespace(id=2, version="^17.2.5", metadata=None),
    ]
    view = _view(f"0x{bytes(32).hex()}")
    updates: list[tuple[int, dict[str, Any]]] = []

    async def fetch_batch(
        rows: list[dict[str, Any]],
        contract_type: str,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        assert [row["id"] for row in rows] == [1, 2]
        assert contract_type == "farm"
        return {"1": view}

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(background, "get_contracts_by_type", lambda _type: contracts)
    monkeypatch.setattr(background, "fetch_contracts_views_batch", fetch_batch)
    monkeypatch.setattr(
        background,
        "update_contract",
        lambda app_id, *, metadata: updates.append((app_id, metadata)),
    )
    monkeypatch.setattr(background.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(background.settings, "update_contracts_chunk_size", 10)

    with caplog.at_level(logging.INFO, logger=background.__name__):
        await background.update_contracts_cache("farm")

    assert updates == [(1, {"cache": view})]
    assert "Updated state cache for 1/2 farm contracts (1 failed, 0 skipped)" in caplog.text
