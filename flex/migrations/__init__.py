from env import settings
from flex.migrations.assets_set_logo_url import assets_set_logo_url_from_tinyman_info


def migrate_before_start() -> None:
    if not settings.migrate:
        return

    assets_set_logo_url_from_tinyman_info()
