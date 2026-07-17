"""Verify Algod and Indexer connectivity without embedding credentials."""

import os
import sys

from algosdk.v2client import algod, indexer
from dotenv import load_dotenv


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def _safe_error(service: str, exc: Exception) -> tuple[bool, str]:
    status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    status_suffix = f' (status {status})' if isinstance(status, int) else ''
    return False, f'{service} check failed: {type(exc).__name__}{status_suffix}'


def verify_algod_client() -> tuple[bool, str]:
    try:
        client = algod.AlgodClient(
            algod_token=_required_env('ALGOD_TOKEN'),
            algod_address=_required_env('ALGOD_ADDRESS'),
            headers={'User-Agent': 'cometa-credential-check'},
        )
        status = client.status()
        return True, f"Algod is healthy at round {status['last-round']}"
    except Exception as exc:
        return _safe_error('Algod', exc)


def verify_indexer_client() -> tuple[bool, str]:
    try:
        client = indexer.IndexerClient(
            indexer_token=_required_env('ALGOD_TOKEN'),
            indexer_address=_required_env('ALGO_INDEXER_ADDRESS'),
            headers={'User-Agent': 'cometa-credential-check'},
        )
        client.health()
        return True, 'Indexer is healthy'
    except Exception as exc:
        return _safe_error('Indexer', exc)


def main() -> int:
    load_dotenv()
    checks = (verify_algod_client(), verify_indexer_client())
    for success, message in checks:
        print(f"{'OK' if success else 'FAIL'}: {message}")
    return 0 if all(success for success, _ in checks) else 1


if __name__ == '__main__':
    sys.exit(main())
