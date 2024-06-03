import logging

from flex import db

logger = logging.getLogger(__name__)


def remove_all_new_models():
    removed_lp_states = db.lp_states.remove_all()
    logger.info(f'Removed {removed_lp_states} LP states')

    # removed_lp_tokens = db.lp_tokens.clear()
    # logger.info(f'Removed {removed_lp_tokens} LP tokens')
    #
    # removed_assets = db.assets.clear()
    # logger.info(f'Removed {removed_assets} assets')
    #
    # removed_asset_prices = db.asset_prices.clear()
    # logger.info(f'Removed {removed_asset_prices} asset prices')
