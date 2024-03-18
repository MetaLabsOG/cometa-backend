from datetime import timedelta

from env import settings


def duration_from_block_count(blocks: int) -> timedelta:
    length_seconds = blocks * settings.block_time
    return timedelta(seconds=length_seconds)


def duration_from_blocks(begin_block: int, end_block: int) -> timedelta:
    if end_block < begin_block:
        raise ValueError(f'End block {end_block} is less than begin block {begin_block}.')
    return duration_from_block_count(end_block - begin_block + 1)
