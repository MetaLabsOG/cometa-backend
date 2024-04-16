import logging

from flex import db


logger = logging.getLogger(__name__)


def asset_add_reserve() -> None:
    logger.info('Adding reserve to assets')

    removed_cnt = db.assets.clear()
    logger.info(f'Removed {removed_cnt} assets')

    # asset_ids = load_all_assets_data()
    # logger.info(f'Loaded {len(asset_ids)} assets')
