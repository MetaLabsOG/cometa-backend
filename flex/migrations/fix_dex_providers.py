import logging

from flex import db
from flex.providers.vestige import is_valid_dex_provider, get_dex_tag_by_name


logger = logging.getLogger(__name__)


def fix_dex_names() -> None:
    logger.info('Fixing dex names.')

    lp_tokens = db.lp_tokens.get_all()
    for lp_token in lp_tokens:
        if not is_valid_dex_provider(lp_token.dex_provider):
            logger.info(f'Invalid DEX in LP token:\n{lp_token.pretty_str()}')
            lp_token.dex_provider = get_dex_tag_by_name(lp_token.dex_provider)
            db.lp_tokens.update(lp_token)

    farming_pools = db.farming_pools.get_all()
    for farming_pool in farming_pools:
        if not is_valid_dex_provider(farming_pool.dex_name):
            logger.info(f'Invalid DEX in farming pool:\n{farming_pool.pretty_str()}')
            farming_pool.dex_name = get_dex_tag_by_name(farming_pool.dex_name)
            db.farming_pools.update(farming_pool)

    lp_states = db.lp_states.get_all()
    for lp_state in lp_states:
        if not is_valid_dex_provider(lp_state.dex_provider):
            logger.info(f'Invalid DEX in LP state:\n{lp_state.pretty_str()}')
            lp_state.dex_provider = get_dex_tag_by_name(lp_state.dex_provider)
            db.lp_states.update(lp_state)

    logger.info('All DEX names are valid now!')
