import logging

from env import settings
from flex.migrations.assets_set_logo_url import assets_set_logo_url_from_tinyman_info
from flex.migrations.lp_upgrades import upgrade_lp_models, set_lp_state_price_algo
from flex.migrations.pool_state_resync import remove_previous_pool_states, apply_creation_txns
from flex.migrations.reset_api_data import remove_all_new_models

logger = logging.getLogger(__name__)


def migrate_before_start() -> None:
    if not settings.migrate:
        return

    logger.info('Migrating sync...')
    remove_previous_pool_states()
    logger.info('DONE sync migration.')


async def migrate_background() -> None:
    if not settings.migrate:
        return

    logger.info('Migrating ASYNC...')
    # await apply_creation_txns()
    logger.info('DONE ASYNC migration.')
