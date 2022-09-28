from bot.utils import usd_format, seconds_format
from core.model import UserPool


def format_user_pool(pool: UserPool) -> str:
    if pool.ended_duration is not None:
        return f'❌<b>{pool.name}.</b>\n' \
               f'Staked = ${usd_format(pool.staked_usd)}, rewards = ${usd_format(pool.reward_usd)}\n' \
               f'<i><b>Withdraw</b> ASAP! It ended {seconds_format(pool.ended_duration)} ago :(</i>\n\n'

    farmed_percent = pool.reward_usd / pool.staked_usd * 100
    text = f'✅<b>{pool.name}</b>, <i>{usd_format(pool.current_apr)}% APR</i>.\n' \
           f'Staked = ${usd_format(pool.staked_usd)}, rewards = ${usd_format(pool.reward_usd)}\n'
    if farmed_percent > 1:
        text += f'<i>You\'ve already farmed <b>{usd_format(farmed_percent)}%</b> from your stake! ' \
                f'Good time for <b>compounding</b>!</i>\n'

    return text
