import logging

from flex import db
from flex.data.lp_states import update_lp_state

logger = logging.getLogger(__name__)


def upgrade_lp_models():
    logger.info('Upgrading LP models')
    all_lp_tokens = db.lp_tokens.get_all()
    all_assets = db.assets.get_all()
    assets_by_id = {asset.id: asset for asset in all_assets}
    for lp_token in all_lp_tokens:
        lp_asset = assets_by_id.get(lp_token.id)
        if lp_asset is None:
            logger.error(f'LP Token {lp_token.id} has no corresponding asset')
            continue
        lp_asset.is_lp_token = True
        db.assets.update(lp_asset)

    logger.info(f'Updated {len(all_lp_tokens)} LP tokens')

    removed_lp_states = db.lp_states.remove_by()
    logger.info(f'Removed {removed_lp_states} LP states')


async def set_lp_state_price_algo():
    all_lp_states = db.lp_states.get_all()
    logger.info(f'Setting {len(all_lp_states)} LP states a price algo')

    updated_lp_states = []
    for lp_state in all_lp_states:
        try:
            if lp_state.token_price_algo is not None:
                continue

            logger.debug(f'Updating LP state {lp_state.id}')
            lp_state = await update_lp_state(lp_state)
            updated_lp_states.append(lp_state)
        except Exception as e:
            logger.error(f'Failed to update LP state {lp_state.id}: {e}', exc_info=True)

    logger.info(f'Updated {len(updated_lp_states)} LP states')
