from bot.utils import usd_format, seconds_format
from core.db.model import UserPool


def calculate_apy(apr: float, periods: int) -> float:
    return (1 + apr / periods) ** periods - 1


def format_user_pool(pool: UserPool) -> str:
    if pool.is_ended():
        return f'💸 <b>{pool.name}.</b>\n' \
               f'Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>.\n' \
               f'<i>It ended {seconds_format(pool.ended_duration)} ago :(</i>\n'

    text = f'💸 <b>{pool.name}</b>, <i>{usd_format(pool.current_apr)}% APR</i>.\n' \
           f'Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>.\n'

    if pool.needs_compound():
        apy = calculate_apy(pool.current_apr / 100, 365) * 100
        text += f'<i><b>Daily</b> compound gives you <b>{usd_format(apy)}%</b> APY!</i>\n'

    return text
