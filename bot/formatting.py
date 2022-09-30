from bot.utils import usd_format, seconds_format
from core.model import UserPool


def calculate_apy(apr: float, periods: int) -> float:
    return (1 + apr / periods) ** periods - 1


def format_user_pool(pool: UserPool) -> str:
    if pool.ended_duration is not None:
        return f'❌<b>{pool.name}.</b>\n' \
               f'💸Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>\n' \
               f'<i><b>Withdraw</b> ASAP! It ended {seconds_format(pool.ended_duration)} ago :(</i>\n'

    farmed_percent = pool.reward_usd / pool.staked_usd * 100
    text = f'✅<b>{pool.name}</b>, <i>{usd_format(pool.current_apr)}% APR</i>.\n' \
           f'💸Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>\n'
    if farmed_percent > 1:
        apy = calculate_apy(pool.current_apr / 100, 365) * 100
        text += f'<i><b>Compound</b> for sure! Already farmed <b>{usd_format(farmed_percent)}%</b> from stake!</i>\n' \
                f'<i>If compounded <b>daily</b>, you would get <b>{usd_format(apy)}%</b> APY!</i>\n'

    return text
