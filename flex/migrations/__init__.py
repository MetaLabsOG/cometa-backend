from env import settings
from flex.migrations.assets_set_logo_url import assets_set_logo_url_from_tinyman_info
from flex.migrations.lp_upgrades import upgrade_lp_models, set_lp_state_price_algo
from flex.migrations.pool_state_resync import remove_previous_data
from flex.migrations.reset_api_data import remove_all_new_models


def migrate_before_start() -> None:
    if not settings.migrate:
        return

    print('Migrating sync...')

    remove_previous_data()

    print('DONE sync migration.')


async def migrate_background() -> None:
    if not settings.migrate:
        return

    print('Migrating ASYNC...')

    print('DONE ASYNC migration.')
