from env import settings
from flex.migrations.assets_set_logo_url import assets_set_logo_url_from_tinyman_info
from flex.migrations.lp_upgrades import upgrade_lp_models, set_lp_state_price_algo


def migrate_before_start() -> None:
    if not settings.migrate:
        return

    print('Migrating sync...')

    assets_set_logo_url_from_tinyman_info()
    upgrade_lp_models()


async def migrate_background() -> None:
    if not settings.migrate:
        return

    print('Migrating ASYNC...')

    await set_lp_state_price_algo()
