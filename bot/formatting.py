from bot.utils import usd_format, seconds_format
from core.model import UserPool


def calculate_apy(apr: float, periods: int) -> float:
    return (1 + apr / periods) ** periods - 1


def format_user_pool(pool: UserPool) -> str:
    if pool.ended_duration is not None:
        return f'💸<b>{pool.name}.</b>\n' \
               f'Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>\n\n' \
               f'❌<i><b>Withdraw</b> ASAP!</i>\n' \
               f'It ended {seconds_format(pool.ended_duration)} ago :(\n'

    farmed_percent = pool.reward_usd / pool.staked_usd * 100
    text = f'💸<b>{pool.name}</b>, <i>{usd_format(pool.current_apr)}% APR</i>.\n' \
           f'Stake = <b>${usd_format(pool.staked_usd)}</b>, rewards = <b>${usd_format(pool.reward_usd)}</b>\n'
    if farmed_percent > 1:
        apy = calculate_apy(pool.current_apr / 100, 365) * 100
        text += f'\n✅<i><b>Compound</b> for sure!</i>\n' \
                f'Already farmed <b>{usd_format(farmed_percent)}%</b> from your stake!\n' \
                f'<i>With <b>daily</b> compound, you will get <b>{usd_format(apy)}%</b> APY!</i>\n'

    return text
