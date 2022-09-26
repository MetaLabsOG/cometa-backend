import json

from env import settings


MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
YEAR_SECONDS = 365 * DAY_SECONDS

BLOCK_TIME = 3.7
BLOCKS_IN_A_YEAR = YEAR_SECONDS / BLOCK_TIME


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)


def get_second_arg(*args, **kwargs):
    return args[1]


def parse_bignum(obj: dict) -> int:
    assert 'type' in obj and 'hex' in obj and obj['type'] == 'BigNumber'
    return int(obj['hex'], 16)


def blocks_to_seconds(start_block: int, last_block: int) -> float:
    assert last_block >= start_block
    return (last_block - start_block + 1) / settings.block_time


def strip_version(version: str) -> str:
    if version[0] == '^':
        return version[1:]
    return version
