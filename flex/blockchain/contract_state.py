"""Decode Cometa Reach contract state directly from Algorand.

The supported farm and distribution contracts were compiled with Reach 0.1.11.
Reach stores the state vector across two or three global byte-slice keys,
depending on the contract version, and each account's four maps in one local
byte-slice key. Keeping the small, validated layout here avoids loading the
legacy Reach JavaScript runtime for read-only operations.
"""

import asyncio
import base64
import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from algosdk import encoding
from algosdk import error as algod_error

from core.util import strip_version
from flex.blockchain.base import algod_client, indexer_client
from flex.blockchain.info import _run_sync

logger = logging.getLogger(__name__)

_CURRENT_REACH_STEP = 4
_LOCAL_MAP_BYTES = 60
_MAX_CONCURRENT_FETCHES = 10
_CLEAR_PROGRAM_SHA256 = "67586e98fad27da0b9968bc039a1ef34c939b9b8e523a8bef89d478608c5ecf6"


class ContractStateDecodeError(RuntimeError):
    """The on-chain state does not match a supported Cometa layout."""


class ContractStateFetchError(RuntimeError):
    """Algorand could not be reached while fetching contract state."""


@dataclass(frozen=True)
class _ContractLayout:
    state_keys: int
    state_size: int
    approval_program_sha256: str
    extra_program_pages: int
    initial_uint_offsets: Mapping[str, int]
    global_uint_offsets: Mapping[str, int]
    global_uint256_offsets: Mapping[str, int]


_LAYOUTS = {
    ("farm", "17.2.4"): _ContractLayout(
        state_keys=2,
        state_size=226,
        approval_program_sha256="869eeea96fa9e17113d15c850d5a1de89dedea88024d0896b346be49af01fd76",
        extra_program_pages=2,
        initial_uint_offsets={
            "creationFee": 32,
            "flatAlgoCreationFee": 40,
            "stakeToken": 48,
            "rewardToken": 56,
            "beginBlock": 64,
            "endBlock": 72,
            "rewardPerBlock": 80,
            "extraAlgoRewardPerBlock": 88,
            "lockLengthBlocks": 96,
        },
        global_uint_offsets={
            "lastUpdateBlock": 128,
            "totalStaked": 176,
        },
        global_uint256_offsets={"rewardPerTokenStored": 136},
    ),
    ("farm", "17.2.5"): _ContractLayout(
        state_keys=3,
        state_size=282,
        approval_program_sha256="732a39988c237fde68632264477f92ab12fd2bb5c2d9fe3c9e27d55945ad8991",
        extra_program_pages=2,
        initial_uint_offsets={
            "creationFee": 32,
            "flatAlgoCreationFee": 40,
            "stakeToken": 48,
            "rewardToken": 56,
            "beginBlock": 64,
            "endBlock": 72,
            "totalRewardAmount": 80,
            "totalAlgoRewardAmount": 88,
            "lockLengthBlocks": 96,
        },
        global_uint_offsets={
            "lastUpdateBlock": 144,
            "totalStaked": 232,
        },
        global_uint256_offsets={"rewardPerTokenStored": 192},
    ),
    ("distribution", "17.0.4"): _ContractLayout(
        state_keys=2,
        state_size=226,
        approval_program_sha256="16a878871b4c644856d2dcdb51f4cdcfa3e8254e063c295d84b7e7922631d219",
        extra_program_pages=1,
        initial_uint_offsets={
            "creationFee": 32,
            "flatAlgoCreationFee": 40,
            "token": 48,
            "beginBlock": 56,
            "endBlock": 64,
            "rewardPerBlock": 72,
            "extraAlgoRewardPerBlock": 80,
            "lockLengthBlocks": 88,
        },
        global_uint_offsets={
            "lastUpdateBlock": 120,
            "totalStaked": 168,
        },
        global_uint256_offsets={"rewardPerTokenStored": 128},
    ),
    ("distribution", "17.0.5"): _ContractLayout(
        state_keys=3,
        state_size=282,
        approval_program_sha256="033fe4cce6eadd05ffd06658bee089194f2585105b9ae31d8874973467cc46fb",
        extra_program_pages=1,
        initial_uint_offsets={
            "creationFee": 32,
            "flatAlgoCreationFee": 40,
            "token": 48,
            "beginBlock": 56,
            "endBlock": 64,
            "totalRewardAmount": 72,
            "totalAlgoRewardAmount": 80,
            "lockLengthBlocks": 88,
        },
        global_uint_offsets={
            "lastUpdateBlock": 136,
            "totalStaked": 224,
        },
        global_uint256_offsets={"rewardPerTokenStored": 184},
    ),
}


def _layout_for(contract_type: str, version: str) -> _ContractLayout:
    normalized_version = strip_version(version)
    layout = _LAYOUTS.get((contract_type, normalized_version))
    if layout is None:
        raise ContractStateDecodeError(f"unsupported {contract_type!r} contract version {normalized_version!r}")
    return layout


def _to_bignum(value: int) -> dict[str, str]:
    """Return the JSON shape produced by ethers.BigNumber."""
    digits = f"{value:x}"
    if len(digits) % 2:
        digits = f"0{digits}"
    return {"type": "BigNumber", "hex": f"0x{digits}"}


def _uint(data: bytes, offset: int, size: int = 8) -> int:
    end = offset + size
    if offset < 0 or end > len(data):
        raise ContractStateDecodeError(f"state field [{offset}:{end}] exceeds {len(data)} available bytes")
    return int.from_bytes(data[offset:end], byteorder="big", signed=False)


def _state_entry_bytes(entries: Sequence[Mapping[str, Any]], key: bytes) -> bytes | None:
    for entry in entries:
        try:
            decoded_key = base64.b64decode(entry["key"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractStateDecodeError("invalid state key encoding") from exc
        if decoded_key != key:
            continue

        value = entry.get("value")
        if not isinstance(value, Mapping) or value.get("type") != 1:
            raise ContractStateDecodeError(f"state key {key.hex()} is not a byte slice")
        encoded = value.get("bytes")
        if not isinstance(encoded, str):
            raise ContractStateDecodeError(f"state key {key.hex()} has no byte value")
        try:
            return base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ContractStateDecodeError(f"state key {key.hex()} has invalid bytes") from exc
    return None


def _recover_global_vector(
    entries: Sequence[Mapping[str, Any]],
    layout: _ContractLayout,
) -> bytes:
    metadata = _state_entry_bytes(entries, b"")
    if metadata is None or len(metadata) < 8:
        raise ContractStateDecodeError("Reach global metadata is missing")
    step = _uint(metadata, 0)
    if step != _CURRENT_REACH_STEP:
        raise ContractStateDecodeError(f"Reach contract is at unsupported step {step}; expected {_CURRENT_REACH_STEP}")

    chunks: list[bytes] = []
    for index in range(layout.state_keys):
        chunk = _state_entry_bytes(entries, bytes([index]))
        if chunk is None:
            raise ContractStateDecodeError(f"Reach global state chunk {index} is missing")
        chunks.append(chunk)

    state = b"".join(chunks)
    if len(state) != layout.state_size:
        raise ContractStateDecodeError(f"Reach global state has {len(state)} bytes; expected {layout.state_size}")
    return state


def _decode_program(params: Mapping[str, Any], name: str) -> bytes:
    encoded = params.get(name)
    if not isinstance(encoded, str):
        raise ContractStateDecodeError(f"application {name} is missing")
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ContractStateDecodeError(f"application {name} is not valid base64") from exc


def _validate_schema(
    params: Mapping[str, Any],
    name: str,
    *,
    byte_slices: int,
) -> None:
    schema = params.get(name)
    if not isinstance(schema, Mapping):
        raise ContractStateDecodeError(f"application {name} is missing")
    num_byte_slices = schema.get("num-byte-slice")
    num_uints = schema.get("num-uint")
    if (
        not isinstance(num_byte_slices, int)
        or isinstance(num_byte_slices, bool)
        or num_byte_slices != byte_slices
        or not isinstance(num_uints, int)
        or isinstance(num_uints, bool)
        or num_uints != 0
    ):
        raise ContractStateDecodeError(f"application {name} does not match the Reach backend")


def _validate_application_identity(
    app_info: Mapping[str, Any],
    app_id: int,
    layout: _ContractLayout,
) -> Mapping[str, Any]:
    returned_id = app_info.get("id")
    if not isinstance(returned_id, int) or isinstance(returned_id, bool) or returned_id != app_id:
        raise ContractStateDecodeError(f"Algorand returned the wrong application for {app_id}")

    params = app_info.get("params")
    if not isinstance(params, Mapping):
        raise ContractStateDecodeError(f"application {app_id} parameters are missing")

    approval_digest = hashlib.sha256(_decode_program(params, "approval-program")).hexdigest()
    if approval_digest != layout.approval_program_sha256:
        raise ContractStateDecodeError(
            f"application {app_id} approval program does not match the declared contract version"
        )

    clear_digest = hashlib.sha256(_decode_program(params, "clear-state-program")).hexdigest()
    if clear_digest != _CLEAR_PROGRAM_SHA256:
        raise ContractStateDecodeError(f"application {app_id} clear-state program does not match the Reach backend")

    extra_pages = params.get("extra-program-pages", 0)
    if not isinstance(extra_pages, int) or isinstance(extra_pages, bool) or extra_pages != layout.extra_program_pages:
        raise ContractStateDecodeError(f"application {app_id} extra program pages do not match the Reach backend")

    _validate_schema(
        params,
        "global-state-schema",
        byte_slices=layout.state_keys + 1,
    )
    _validate_schema(params, "local-state-schema", byte_slices=1)
    return params


def decode_contract_views(
    entries: Sequence[Mapping[str, Any]],
    contract_type: str,
    version: str,
) -> dict[str, dict[str, Any]]:
    """Decode a supported contract's global state into its public view shape."""
    layout = _layout_for(contract_type, version)
    state = _recover_global_vector(entries, layout)

    initial: dict[str, Any] = {
        "beneficiary": f"0x{state[:32].hex()}",
        **{field: _to_bignum(_uint(state, offset)) for field, offset in layout.initial_uint_offsets.items()},
    }
    global_view: dict[str, Any] = {
        **{field: _to_bignum(_uint(state, offset)) for field, offset in layout.global_uint_offsets.items()},
        **{field: _to_bignum(_uint(state, offset, size=32)) for field, offset in layout.global_uint256_offsets.items()},
    }
    return {"initial": initial, "global": global_view}


def _decode_optional_uint(data: bytes, offset: int, size: int) -> int:
    tag = data[offset]
    if tag == 0:
        return 0
    if tag != 1:
        raise ContractStateDecodeError(f"invalid Reach Maybe tag {tag} at byte {offset}")
    return _uint(data, offset + 1, size)


def decode_local_view(entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """Decode Reach's four per-account maps into the legacy local view shape."""
    encoded = _state_entry_bytes(entries, b"\x00")
    if encoded is None:
        encoded = bytes(_LOCAL_MAP_BYTES)
    if len(encoded) != _LOCAL_MAP_BYTES:
        raise ContractStateDecodeError(f"Reach local state has {len(encoded)} bytes; expected {_LOCAL_MAP_BYTES}")
    state = encoded

    values = {
        "staked": _decode_optional_uint(state, 0, 8),
        "reward": _decode_optional_uint(state, 9, 8),
        "lockTimestamp": _decode_optional_uint(state, 18, 8),
        "rewardPerTokenPaid": _decode_optional_uint(state, 27, 32),
    }
    return {field: _to_bignum(value) for field, value in values.items()}


async def _fetch_global_entries(
    app_id: int,
    layout: _ContractLayout,
) -> Sequence[Mapping[str, Any]]:
    try:
        app_info = await _run_sync(algod_client.application_info, app_id)
    except algod_error.AlgodHTTPError as exc:
        if exc.code == 404:
            raise ContractStateDecodeError(f"application {app_id} was not found") from exc
        raise ContractStateFetchError(f"failed to fetch application {app_id}") from exc
    except Exception as exc:
        raise ContractStateFetchError(f"failed to fetch application {app_id}") from exc

    if not isinstance(app_info, Mapping):
        raise ContractStateDecodeError(f"application {app_id} response is malformed")
    params = _validate_application_identity(app_info, app_id, layout)
    entries = params.get("global-state", [])
    if not isinstance(entries, list) or not entries:
        raise ContractStateDecodeError(f"application {app_id} has no global state")
    return entries


async def fetch_contract_views(
    app_id: int,
    contract_type: str,
    version: str,
) -> dict[str, dict[str, Any]]:
    """Fetch and decode one supported Cometa contract."""
    layout = _layout_for(contract_type, version)
    entries = await _fetch_global_entries(app_id, layout)
    return decode_contract_views(entries, contract_type, version)


async def fetch_contracts_views_batch(
    id_versions: Sequence[Mapping[str, Any]],
    contract_type: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Fetch several contracts concurrently while isolating per-contract failures."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

    async def fetch_one(item: Mapping[str, Any]) -> tuple[int, dict[str, dict[str, Any]] | None]:
        try:
            raw_app_id = item["id"]
            if isinstance(raw_app_id, bool):
                raise ValueError("application ID must be a positive integer")
            app_id = int(raw_app_id)
            if app_id <= 0:
                raise ValueError("application ID must be a positive integer")
            version = str(item["version"])
            async with semaphore:
                return app_id, await fetch_contract_views(app_id, contract_type, version)
        except Exception as exc:
            logger.warning("Failed to fetch state for app %s: %s", item.get("id"), exc)
            return -1, None

    pairs = await asyncio.gather(*(fetch_one(item) for item in id_versions))
    return {str(app_id): views for app_id, views in pairs if views is not None}


async def fetch_contract_local_views(
    address: str,
    contracts: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, str]]]:
    """Fetch an account once and decode local views for supported contracts."""
    if not encoding.is_valid_address(address):
        raise ValueError("invalid Algorand address")

    requested_ids: set[int] = set()
    for contract in contracts:
        try:
            raw_app_id = contract["id"]
            if isinstance(raw_app_id, bool):
                raise ValueError("application ID must be a positive integer")
            app_id = int(raw_app_id)
            if app_id <= 0:
                raise ValueError("application ID must be a positive integer")
            _layout_for(str(contract["type"]), str(contract["version"]))
            requested_ids.add(app_id)
        except (KeyError, TypeError, ValueError, ContractStateDecodeError) as exc:
            logger.warning("Ignoring invalid local-state contract %s: %s", contract.get("id"), exc)

    if not requested_ids:
        return {}

    try:
        response = await _run_sync(indexer_client.account_info, address)
    except Exception as exc:
        raise RuntimeError(f"failed to fetch local state for {address}: {exc}") from exc

    if not isinstance(response, Mapping):
        raise ContractStateDecodeError("account response is malformed")
    account = response.get("account", response)
    if not isinstance(account, Mapping):
        raise ContractStateDecodeError("account payload is malformed")
    local_states = account.get("apps-local-state", [])
    if not isinstance(local_states, list):
        raise ContractStateDecodeError("account local state response is malformed")

    result: dict[str, dict[str, dict[str, str]]] = {}
    for app_state in local_states:
        if not isinstance(app_state, Mapping):
            logger.warning("Ignoring malformed application local state")
            continue
        raw_local_app_id = app_state.get("id")
        if not isinstance(raw_local_app_id, int) or isinstance(raw_local_app_id, bool) or raw_local_app_id <= 0:
            logger.warning("Ignoring application local state with invalid ID")
            continue
        local_app_id = raw_local_app_id
        if local_app_id not in requested_ids or app_state.get("deleted", False):
            continue
        entries = app_state.get("key-value") or []
        if not isinstance(entries, list):
            logger.warning("Ignoring malformed local state for application %s", local_app_id)
            continue
        try:
            result[str(local_app_id)] = decode_local_view(entries)
        except ContractStateDecodeError as exc:
            logger.warning("Ignoring malformed local state for application %s: %s", local_app_id, exc)
    return result
