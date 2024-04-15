from datetime import timedelta, datetime

from blockchain.indexer import indexer_client
from env import settings


def duration_from_block_count(blocks: int) -> timedelta:
    length_seconds = blocks * settings.block_time
    return timedelta(seconds=length_seconds)


def duration_from_blocks(begin_block: int, end_block: int) -> timedelta:
    if end_block < begin_block:
        raise ValueError(f'End block {end_block} is less than begin block {begin_block}.')
    return duration_from_block_count(end_block - begin_block + 1)


def date_from_block(round_num: int, current_round_num: int, current_date: datetime) -> datetime:
    if round_num > current_round_num:
        pool_time_remains = duration_from_blocks(current_round_num, round_num)
        return current_date + pool_time_remains

    round_info = indexer_client.block_info(round_num=round_num, header_only=True)
    timestamp = round_info['timestamp']
    return datetime.fromtimestamp(timestamp)
