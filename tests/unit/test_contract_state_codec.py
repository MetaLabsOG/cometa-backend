import asyncio
import base64
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from algosdk import encoding
from algosdk import error as algod_error

from blockchain.indexer import _has_active_reach_local_state
from flex.blockchain import contract_state
from flex.blockchain.contract_state import (
    ContractStateDecodeError,
    ContractStateFetchError,
    decode_contract_views,
    decode_local_view,
    fetch_contract_local_views,
    fetch_contract_views,
    fetch_contracts_views_batch,
)


def _entry(key: bytes, value: bytes, *, value_type: int = 1) -> dict[str, Any]:
    encoded_value: dict[str, Any] = {"type": value_type}
    if value_type == 1:
        encoded_value["bytes"] = base64.b64encode(value).decode()
    return {
        "key": base64.b64encode(key).decode(),
        "value": encoded_value,
    }


def _put_uint(state: bytearray, offset: int, value: int, size: int = 8) -> None:
    state[offset : offset + size] = value.to_bytes(size, byteorder="big")


def _global_entries(state: bytes, *, chunks: int) -> list[dict[str, Any]]:
    metadata = (4).to_bytes(8, byteorder="big") + bytes(16)
    chunk_size = 127
    entries = [_entry(bytes([index]), state[index * chunk_size : (index + 1) * chunk_size]) for index in range(chunks)]
    return [entries[-1], _entry(b"", metadata), *entries[:-1], _entry(b"extra", b"ignored")]


def _application_info(
    *,
    app_id: int,
    state: bytes,
    approval_program: bytes,
    state_keys: int,
    extra_program_pages: int,
) -> dict[str, Any]:
    return {
        "id": app_id,
        "params": {
            "approval-program": base64.b64encode(approval_program).decode(),
            "clear-state-program": base64.b64encode(b"\x06").decode(),
            "extra-program-pages": extra_program_pages,
            "global-state-schema": {
                "num-byte-slice": state_keys + 1,
                "num-uint": 0,
            },
            "local-state-schema": {
                "num-byte-slice": 1,
                "num-uint": 0,
            },
            "global-state": _global_entries(state, chunks=state_keys),
        },
    }


def test_decodes_current_farm_global_views_with_exact_reach_shape() -> None:
    state = bytearray(282)
    beneficiary = bytes.fromhex("6126029bb408ffc12a0542001b3190bc79d4fc207ed55f06b1dd7eb1bda0229a")
    state[:32] = beneficiary
    values = {
        32: 100,
        40: 100_000_000,
        48: 1_017_284_319,
        56: 923_640_017,
        64: 36_080_746,
        72: 46_000_746,
        80: 14_000_000,
        88: 0,
        96: 959_999,
        144: 46_000_746,
        232: 22_386_581,
    }
    for offset, value in values.items():
        _put_uint(state, offset, value)
    _put_uint(state, 192, 104_721_732_208_908_362, size=32)

    views = decode_contract_views(_global_entries(state, chunks=3), "farm", "^17.2.5")

    assert views == {
        "initial": {
            "beneficiary": f"0x{beneficiary.hex()}",
            "creationFee": {"type": "BigNumber", "hex": "0x64"},
            "flatAlgoCreationFee": {"type": "BigNumber", "hex": "0x05f5e100"},
            "stakeToken": {"type": "BigNumber", "hex": "0x3ca286df"},
            "rewardToken": {"type": "BigNumber", "hex": "0x370da0d1"},
            "beginBlock": {"type": "BigNumber", "hex": "0x02268c6a"},
            "endBlock": {"type": "BigNumber", "hex": "0x02bdea6a"},
            "totalRewardAmount": {"type": "BigNumber", "hex": "0xd59f80"},
            "totalAlgoRewardAmount": {"type": "BigNumber", "hex": "0x00"},
            "lockLengthBlocks": {"type": "BigNumber", "hex": "0x0ea5ff"},
        },
        "global": {
            "lastUpdateBlock": {"type": "BigNumber", "hex": "0x02bdea6a"},
            "totalStaked": {"type": "BigNumber", "hex": "0x01559795"},
            "rewardPerTokenStored": {
                "type": "BigNumber",
                "hex": "0x01740bdc5093584a",
            },
        },
    }


def test_decodes_current_distribution_global_views() -> None:
    state = bytearray(282)
    beneficiary = bytes(range(32))
    state[:32] = beneficiary
    values = {
        32: 100,
        40: 100_000_000,
        48: 924_268_058,
        56: 32_726_840,
        64: 42_283_203,
        72: 10_000_000_000_000,
        80: 0,
        88: 785_454,
        136: 42_283_203,
        224: 2_584_523_079_432,
    }
    for offset, value in values.items():
        _put_uint(state, offset, value)
    _put_uint(state, 184, 1_608_638_085_696_333_828, size=32)

    views = decode_contract_views(
        _global_entries(state, chunks=3),
        "distribution",
        "17.0.5",
    )

    assert views["initial"] == {
        "beneficiary": f"0x{beneficiary.hex()}",
        "creationFee": {"type": "BigNumber", "hex": "0x64"},
        "flatAlgoCreationFee": {"type": "BigNumber", "hex": "0x05f5e100"},
        "token": {"type": "BigNumber", "hex": "0x3717361a"},
        "beginBlock": {"type": "BigNumber", "hex": "0x01f35f38"},
        "endBlock": {"type": "BigNumber", "hex": "0x028530c3"},
        "totalRewardAmount": {"type": "BigNumber", "hex": "0x09184e72a000"},
        "totalAlgoRewardAmount": {"type": "BigNumber", "hex": "0x00"},
        "lockLengthBlocks": {"type": "BigNumber", "hex": "0x0bfc2e"},
    }
    assert views["global"] == {
        "lastUpdateBlock": {"type": "BigNumber", "hex": "0x028530c3"},
        "totalStaked": {"type": "BigNumber", "hex": "0x0259c1947f08"},
        "rewardPerTokenStored": {
            "type": "BigNumber",
            "hex": "0x165307d0e6182804",
        },
    }


@pytest.mark.parametrize(
    ("contract_type", "version", "state_size", "chunks", "offsets"),
    [
        (
            "farm",
            "17.2.4",
            226,
            2,
            {
                "rewardPerBlock": 80,
                "extraAlgoRewardPerBlock": 88,
                "lastUpdateBlock": 128,
                "rewardPerTokenStored": 136,
                "totalStaked": 176,
            },
        ),
        (
            "distribution",
            "17.0.4",
            226,
            2,
            {
                "rewardPerBlock": 72,
                "extraAlgoRewardPerBlock": 80,
                "lastUpdateBlock": 120,
                "rewardPerTokenStored": 128,
                "totalStaked": 168,
            },
        ),
    ],
)
def test_decodes_legacy_supported_layouts(
    contract_type: str,
    version: str,
    state_size: int,
    chunks: int,
    offsets: Mapping[str, int],
) -> None:
    state = bytearray(state_size)
    state[:32] = bytes(range(32))
    for index, (field, offset) in enumerate(offsets.items(), start=1):
        size = 32 if field == "rewardPerTokenStored" else 8
        _put_uint(state, offset, index, size=size)

    views = decode_contract_views(
        _global_entries(state, chunks=chunks),
        contract_type,
        version,
    )

    assert views["initial"]["rewardPerBlock"]["hex"] == "0x01"
    assert views["initial"]["extraAlgoRewardPerBlock"]["hex"] == "0x02"
    assert views["global"]["lastUpdateBlock"]["hex"] == "0x03"
    assert views["global"]["rewardPerTokenStored"]["hex"] == "0x04"
    assert views["global"]["totalStaked"]["hex"] == "0x05"


def test_decodes_live_local_state_fixture() -> None:
    encoded = base64.b64decode("AQAAAAukO3QAAQAAAAAAAAAAAQAAAAADh7/vAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABkXmhu99dq")

    view = decode_local_view([_entry(b"\x00", encoded)])

    assert view == {
        "staked": {"type": "BigNumber", "hex": "0x0ba43b7400"},
        "reward": {"type": "BigNumber", "hex": "0x00"},
        "lockTimestamp": {"type": "BigNumber", "hex": "0x0387bfef"},
        "rewardPerTokenPaid": {
            "type": "BigNumber",
            "hex": "0x645e686ef7d76a",
        },
    }


def test_missing_local_map_decodes_to_reach_defaults() -> None:
    assert decode_local_view([]) == {
        "staked": {"type": "BigNumber", "hex": "0x00"},
        "reward": {"type": "BigNumber", "hex": "0x00"},
        "lockTimestamp": {"type": "BigNumber", "hex": "0x00"},
        "rewardPerTokenPaid": {"type": "BigNumber", "hex": "0x00"},
    }


def test_active_local_state_lookup_does_not_depend_on_key_order() -> None:
    active = bytearray(60)
    active[0] = 1
    _put_uint(active, 1, 1)
    entries = [
        _entry(b"unrelated", b"value"),
        _entry(b"\x00", bytes(active)),
    ]

    assert _has_active_reach_local_state(entries) is True
    assert _has_active_reach_local_state([{"key": "invalid"}, *entries]) is True
    assert _has_active_reach_local_state([_entry(b"\x00", bytes(60))]) is False
    assert _has_active_reach_local_state([]) is False


@pytest.mark.parametrize(
    "entries",
    [
        [_entry(b"\x00", bytes(59))],
        [_entry(b"\x00", bytes(61))],
        [_entry(b"\x00", bytes([2]) + bytes(59))],
        [_entry(b"\x00", b"", value_type=2)],
    ],
)
def test_rejects_malformed_local_state(entries: list[dict[str, Any]]) -> None:
    with pytest.raises(ContractStateDecodeError):
        decode_local_view(entries)


def test_rejects_unknown_contract_version_and_global_step() -> None:
    state = bytes(282)

    with pytest.raises(ContractStateDecodeError, match="unsupported"):
        decode_contract_views(_global_entries(state, chunks=3), "farm", "18.0.0")

    entries = _global_entries(state, chunks=3)
    entries = [
        _entry(b"", (3).to_bytes(8, byteorder="big") + bytes(16)) if base64.b64decode(entry["key"]) == b"" else entry
        for entry in entries
    ]
    with pytest.raises(ContractStateDecodeError, match="unsupported step"):
        decode_contract_views(entries, "farm", "17.2.5")


@pytest.mark.asyncio
async def test_fetch_validates_canonical_program_and_schema(monkeypatch) -> None:
    app_id = 55
    approval_program = b"canonical farm program"
    state = bytes(282)
    key = ("farm", "17.2.5")
    layout = replace(
        contract_state._LAYOUTS[key],
        approval_program_sha256=hashlib.sha256(approval_program).hexdigest(),
    )
    monkeypatch.setitem(contract_state._LAYOUTS, key, layout)

    app_info = _application_info(
        app_id=app_id,
        state=state,
        approval_program=approval_program,
        state_keys=layout.state_keys,
        extra_program_pages=layout.extra_program_pages,
    )

    async def fake_run_sync(function, *args):
        return app_info

    monkeypatch.setattr(contract_state, "_run_sync", fake_run_sync)

    views = await fetch_contract_views(app_id, "farm", "17.2.5")
    assert views["initial"]["beneficiary"] == f"0x{bytes(32).hex()}"

    app_info["params"]["approval-program"] = base64.b64encode(b"spoofed").decode()
    with pytest.raises(ContractStateDecodeError, match="approval program"):
        await fetch_contract_views(app_id, "farm", "17.2.5")


@pytest.mark.asyncio
async def test_fetch_distinguishes_provider_failure(monkeypatch) -> None:
    async def failed_run_sync(function, *args):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(contract_state, "_run_sync", failed_run_sync)

    with pytest.raises(ContractStateFetchError):
        await fetch_contract_views(55, "farm", "17.2.5")


@pytest.mark.asyncio
async def test_fetch_classifies_missing_application_as_contract_mismatch(monkeypatch) -> None:
    async def missing_run_sync(function, *args):
        raise algod_error.AlgodHTTPError("application does not exist", code=404)

    monkeypatch.setattr(contract_state, "_run_sync", missing_run_sync)

    with pytest.raises(ContractStateDecodeError, match="not found"):
        await fetch_contract_views(55, "farm", "17.2.5")


@pytest.mark.asyncio
async def test_batch_bounds_concurrency_and_isolates_invalid_rows(monkeypatch) -> None:
    active = 0
    max_active = 0

    async def fake_fetch(app_id: int, contract_type: str, version: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.001)
        active -= 1
        return {"initial": {"id": app_id}, "global": {}}

    monkeypatch.setattr(contract_state, "fetch_contract_views", fake_fetch)
    rows = [{"id": app_id, "version": "17.2.5"} for app_id in range(1, 26)]
    rows.extend(
        [
            {"id": -1, "version": "17.2.5"},
            {"id": True, "version": "17.2.5"},
            {"id": 26},
        ]
    )

    result = await fetch_contracts_views_batch(rows, "farm")

    assert len(result) == 25
    assert max_active == contract_state._MAX_CONCURRENT_FETCHES


@pytest.mark.asyncio
async def test_local_fetch_reads_account_once_and_filters_apps(monkeypatch) -> None:
    address = encoding.encode_address(bytes(32))
    encoded = bytearray(60)
    encoded[0] = 1
    _put_uint(encoded, 1, 42)
    calls = 0

    async def fake_run_sync(function, *args):
        nonlocal calls
        calls += 1
        return {
            "account": {
                "apps-local-state": [
                    "malformed",
                    {
                        "id": 11,
                        "key-value": [_entry(b"\x00", bytes(encoded))],
                    },
                    {
                        "id": 12,
                        "deleted": True,
                        "key-value": [_entry(b"\x00", bytes(encoded))],
                    },
                    {
                        "id": 13,
                        "key-value": [_entry(b"\x00", bytes(59))],
                    },
                    {
                        "id": 99,
                        "key-value": [_entry(b"\x00", bytes(encoded))],
                    },
                ]
            }
        }

    monkeypatch.setattr(contract_state, "_run_sync", fake_run_sync)

    result = await fetch_contract_local_views(
        address,
        [
            {"id": 11, "type": "farm", "version": "17.2.5"},
            {"id": 12, "type": "distribution", "version": "17.0.5"},
            {"id": 13, "type": "farm", "version": "17.2.5"},
            {"id": 14, "type": "farm", "version": "unsupported"},
        ],
    )

    assert calls == 1
    assert set(result) == {"11"}
    assert result["11"]["staked"]["hex"] == "0x2a"


@pytest.mark.asyncio
async def test_local_fetch_validates_address_before_network(monkeypatch) -> None:
    async def unexpected_run_sync(function, *args):
        raise AssertionError("network should not be called")

    monkeypatch.setattr(contract_state, "_run_sync", unexpected_run_sync)

    with pytest.raises(ValueError, match="invalid Algorand address"):
        await fetch_contract_local_views(
            "invalid",
            [{"id": 11, "type": "farm", "version": "17.2.5"}],
        )
