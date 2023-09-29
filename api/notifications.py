import logging
from datetime import timedelta
from typing import Optional

from discord_webhook import DiscordWebhook
from telegram.constants import ParseMode
from telegram.ext import Application

from api.db_model import ContractType
from blockchain.indexer import get_asset
from env import settings

application = Application.builder().token(settings.telegram_bot_api_token).build()
bot = application.bot

logger = logging.getLogger(__name__)


async def notify_telegram_chat(chat_id: int, text: str):
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML
    )


async def notify_cometa_telegram_channel(text: str):
    return await notify_telegram_chat(settings.telegram_channel_id, text)


def notify_discord_webhook(text: str):
    if settings.discord_notify_webhook_url is None:
        return
    webhook = DiscordWebhook(url=settings.discord_notify_webhook_url, content=text)
    response = webhook.execute()
    print(response)



def duration_from_blocks(blocks: int) -> timedelta:
    length_seconds = blocks * settings.block_time
    return timedelta(seconds=length_seconds)


async def announce_farm(
        duration: timedelta,
        lock_duration: timedelta,
        metadata: dict
) -> None:
    # TODO: ONE ASSET CASE (staking)

    lp_token_id = metadata['stake_token_id']
    asset1_id = metadata['asset1_id']
    asset2_id = metadata['asset2_id']
    reward_token_id = metadata['reward_token_id']

    lp_token = get_asset(int(lp_token_id))
    asset1 = get_asset(int(asset1_id))
    asset2 = get_asset(int(asset2_id))
    reward_token = get_asset(int(reward_token_id))

    asset1_name = asset1['params']['unit-name']
    asset2_name = asset2['params']['unit-name']
    reward_token_name = reward_token['params']['unit-name']
    lp_pool_address = lp_token['params']['reserve']

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
        asset1_link = f'<a href="https://vestige.fi/asset/{asset1_id}">{asset1_name}</a>' if asset1_id != 0 else 'ALGO'
        asset2_link = f'<a href="https://vestige.fi/asset/{asset2_id}">{asset2_name}</a>' if asset2_id != 0 else 'ALGO'
        telegram_text = f'''
💥 New FARMING pool on Cometa!

💸 {asset1_link}/{asset2_link} ⟶ <a href="https://vestige.fi/asset/{reward_token_id}">{reward_token_name}</a>

<a href="https://app.tinyman.org/#/pool/{lp_pool_address}/add-liquidity">Buy LP tokens on Tinyman.</a>

⏳ <b>{duration.days} days</b>
{lock_str}
<i>Don't miss it and enjoy farming!</i> ❤️

☄️ https://app.cometa.farm/
        '''
        await notify_cometa_telegram_channel(telegram_text)
    except Exception as e:
        logger.exception(e)

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
        asset1_link = f'<a href="https://vestige.fi/asset/{asset1_id}">{asset1_name}</a>' if asset1_id != 0 else 'ALGO'
        asset2_link = f'<a href="https://vestige.fi/asset/{asset2_id}">{asset2_name}</a>' if asset2_id != 0 else 'ALGO'
        discord_text = f'''
💥 New FARMING pool on Cometa!

💸 {asset1_link}/{asset2_link} ⟶ <a href="https://vestige.fi/asset/{reward_token_id}">{reward_token_name}</a>

<a href="https://app.tinyman.org/#/pool/{lp_pool_address}/add-liquidity">Buy LP tokens on Tinyman.</a>

⏳ <b>{duration.days} days</b>
{lock_str}
<i>Don't miss it and enjoy farming!</i> ❤️

☄️ https://app.cometa.farm/
        '''
        notify_discord_webhook(discord_text)
    except Exception as e:
        logger.exception(e)


async def announce_distribution(
        duration: timedelta,
        lock_duration: timedelta,
        metadata: dict
) -> None:
    stake_token_id = metadata['stake_token_id']
    stake_token = get_asset(int(stake_token_id))
    stake_token_name = stake_token['params']['unit-name']

    lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
    token_link = f'<a href="https://vestige.fi/asset/{stake_token_id}">{stake_token_name}</a>'
    token_buy_link = 'https://app.cometa.farm/swap'

    try:
        telegram_text = f'''
💥 New STAKING pool on Cometa!

💸 {token_link} ⟶ {token_link}

<a href="{token_buy_link}">Buy {stake_token_name} on Cometa Swap.</a>

⏳ <b>{duration.days} days</b>
{lock_str}
<i>Don't miss it and enjoy farming!</i> ❤️

☄️ https://app.cometa.farm/
    '''
        await notify_cometa_telegram_channel(telegram_text)
    except Exception as e:
        logger.exception(e)

    try:
        discord_text = f'''
💥 New STAKING pool on Cometa!

💸 {token_link} ⟶ {token_link}

<a href="{token_buy_link}">Buy {stake_token_name} on Cometa Swap.</a>

⏳ <b>{duration.days} days</b>
{lock_str}
<i>Don't miss it and enjoy farming!</i> ❤️

☄️ https://app.cometa.farm/
    '''
        notify_discord_webhook(discord_text)
    except Exception as e:
        logger.exception(e)


# TODO: show additional algo rewards
# TODO: show projected APY
async def notify_new_pool(
        begin_block: int,
        end_block: int,
        lock_length_blocks: int,
        type: str,
        metadata: Optional[dict] = None
):
    duration = duration_from_blocks(end_block - begin_block + 1)
    lock_duration = duration_from_blocks(lock_length_blocks)

    if type == ContractType.FARM:
        return await announce_farm(duration, lock_duration, metadata)
    elif type == ContractType.DISTRIBUTION:
        return await announce_distribution(duration, lock_duration, metadata)
    else:
        raise Exception(f'Unknown contract type: {type}')
