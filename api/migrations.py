import logging
from datetime import datetime

from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.db.contracts import get_all_pool_contracts, update_contract_with
from core.db.model import ContractInfo
from core.decorators import safe_async_method
from core.util import parse_bignum

logger = logging.getLogger(__name__)


def update_contract_start_end_dates(contract: ContractInfo) -> ContractInfo | None:
    start_time = datetime.now()
    current_block = get_current_round()

    metadata = contract.metadata
    if metadata is None:
        logger.warning(f'Contract has no metadata: {contract}')
        return None

    cache = metadata.get('cache')
    logger.info(f'Updating pool {contract.id}...')

    end_block = metadata.get('end_block')
    if end_block is None:
        end_block = parse_bignum(cache['initial']['endBlock'])
        metadata['end_block'] = end_block
        logger.info(f'Updated end block for {contract.id} to {end_block}')

    begin_block = metadata.get('begin_block')
    if begin_block is None and cache is not None:
        begin_block = parse_bignum(cache['initial']['beginBlock'])
        metadata['begin_block'] = begin_block
        logger.info(f'Updated begin block for {contract.id} to {begin_block}')

    if metadata.get('end_date') is None:
        end_date = date_from_block(end_block, current_block, start_time)
        metadata['end_date'] = end_date
        contract.end_date = end_date
        logger.info(f'Updated end date for {contract.id} to {end_date}')

    if metadata.get('begin_date') is None:
        begin_date = date_from_block(begin_block, current_block, start_time)
        metadata['begin_date'] = begin_date
        contract.begin_date = begin_date
        logger.info(f'Updated begin date for {contract.id} to {begin_date}')

    if metadata.get('lock_length_blocks') is None and cache is not None:
        lock_length_blocks = parse_bignum(cache['initial']['lockLengthBlocks'])
        metadata['lock_length_blocks'] = lock_length_blocks
        logger.info(f'Updated lock length blocks for {contract.id} to {lock_length_blocks}')

    update_contract_with(
        contract_id=contract.id,
        metadata=metadata,
        begin_date=contract.begin_date,
        end_date=contract.end_date
    )

    logger.info(f'Pool {contract.id} updated: {contract.begin_date} - {contract.end_date}.')


@safe_async_method
async def update_pool_start_end_dates() -> None:
    start_time = datetime.now()
    current_block = get_current_round()
    logger.info(f'Migrating pools info. Current block: {current_block}, start time: {start_time}.')

    all_contracts = get_all_pool_contracts()
    logger.info(f'Found {len(all_contracts)} contracts.')

    for contract in all_contracts:
        try:
            if contract.begin_date is not None and contract.end_date is not None:
                logger.info(f'Skipping pool {contract.id}...')
                continue

            contract = update_contract_start_end_dates(contract)

            if contract is not None:
                update_contract_with(
                    contract_id=contract.id,
                    metadata=contract.metadata,
                    begin_date=contract.begin_date,
                    end_date=contract.end_date
                )

            logger.info(f'Pool {contract.id} updated: {contract.begin_date} - {contract.end_date}.')

        except Exception as e:
            logger.error(f'Failed to update pool {contract.id}: {e}', exc_info=True)
            continue
