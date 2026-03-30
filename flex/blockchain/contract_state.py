"""Read Algorand application global state via algosdk.

Replaces JS interop (Reach stdlib) for reading contract views.
Produces BigNumber-compatible format for backward compatibility with parse_cache().
"""

import base64
import logging

from algosdk import encoding

from flex.blockchain.base import algod_client
from flex.blockchain.info import _run_sync

logger = logging.getLogger(__name__)

# Keys that are uint64 values in Reach farm/distribution contracts
UINT64_KEYS = {
    'stakeToken', 'rewardToken', 'beginBlock', 'endBlock',
    'rewardAmount', 'lockLengthBlocks', 'totalStaked',
    'lastConsensusTime',
}

# Keys that are byte-encoded addresses
ADDRESS_KEYS = {'beneficiary'}


def _decode_state_key(key_b64: str) -> str:
    return base64.b64decode(key_b64).decode('utf-8', errors='replace')


def _to_bignum(value: int) -> dict:
    """Convert int to Reach-compatible BigNumber format."""
    return {'type': 'BigNumber', 'hex': hex(value)}


def _address_from_bytes(raw_bytes: bytes) -> str:
    """Convert raw 32-byte public key to Algorand address string."""
    return encoding.encode_address(raw_bytes)


def _parse_global_state(global_state: list[dict]) -> dict[str, any]:
    """Parse AVM global state key-value pairs into a Python dict.

    Returns raw values: int for uint64, bytes for byte slices.
    """
    result = {}
    for kv in global_state:
        key = _decode_state_key(kv['key'])
        value = kv['value']
        if value['type'] == 2:  # uint64
            result[key] = value['uint']
        elif value['type'] == 1:  # byte slice
            result[key] = base64.b64decode(value['bytes'])
    return result


def _to_bignum_format(raw_state: dict) -> dict:
    """Convert raw state dict to BigNumber-compatible format for parse_cache()."""
    result = {}
    for key, value in raw_state.items():
        if key in UINT64_KEYS:
            result[key] = _to_bignum(value if isinstance(value, int) else 0)
        elif key in ADDRESS_KEYS:
            if isinstance(value, bytes) and len(value) == 32:
                result[key] = '0x' + value.hex()
            else:
                result[key] = value
        else:
            if isinstance(value, int):
                result[key] = _to_bignum(value)
            elif isinstance(value, bytes):
                result[key] = '0x' + value.hex()
    return result


async def fetch_app_global_state(app_id: int) -> dict:
    """Fetch raw global state for an Algorand application.

    Returns dict with decoded key names and raw values (int/bytes).
    Raises RuntimeError if application not found or has no global state.
    """
    try:
        app_info = await _run_sync(algod_client.application_info, app_id)
    except Exception as e:
        raise RuntimeError(f'Failed to fetch application {app_id}: {e}') from e

    params = app_info.get('params', {})
    global_state = params.get('global-state', [])
    if not global_state:
        raise RuntimeError(f'Application {app_id} has no global state')

    return _parse_global_state(global_state)


async def fetch_contract_views(app_id: int) -> dict:
    """Fetch contract state and return in the same format as JS interop.

    Returns:
        {
            'initial': {BigNumber-format fields},
            'global': {BigNumber-format fields}
        }

    Compatible with existing parse_cache() and metadata consumers.
    """
    raw_state = await fetch_app_global_state(app_id)
    bignum_state = _to_bignum_format(raw_state)

    # Split into initial (immutable) and global (mutable) views
    # matching Reach contract convention
    initial_keys = {
        'stakeToken', 'rewardToken', 'beginBlock', 'endBlock',
        'rewardAmount', 'lockLengthBlocks', 'beneficiary',
    }
    global_keys = {'totalStaked', 'lastConsensusTime'}

    initial = {k: v for k, v in bignum_state.items() if k in initial_keys}
    global_view = {k: v for k, v in bignum_state.items() if k in global_keys}

    # Any remaining keys go to global
    for k, v in bignum_state.items():
        if k not in initial_keys and k not in global_keys:
            global_view[k] = v

    return {'initial': initial, 'global': global_view}


async def fetch_contracts_views_batch(
    id_versions: list[dict],
) -> dict[str, dict]:
    """Fetch views for multiple contracts, keyed by string contract ID.

    Drop-in replacement for calljs("fetchContractsGlobalViews", ...).
    On per-contract failure, logs warning and skips that contract.
    """
    result = {}
    for item in id_versions:
        app_id = item['id']
        try:
            views = await fetch_contract_views(app_id)
            result[str(app_id)] = views
        except Exception as e:
            logger.warning(f'Failed to fetch state for app {app_id}: {e}')
    return result
