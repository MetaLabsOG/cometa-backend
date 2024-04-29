import logging

from flex import db
from flex.data.lp_states import update_lp_state

logger = logging.getLogger(__name__)


def upgrade_lp_models():
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
