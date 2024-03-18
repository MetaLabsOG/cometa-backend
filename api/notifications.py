import logging
from datetime import timedelta
from typing import Optional

from discord_webhook import DiscordWebhook
from telegram.constants import ParseMode
from telegram.ext import Application

from api.db_model import ContractType
from blockchain.indexer import get_asset
from blockchain.util import duration_from_block_count
from env import settings

application = Application.builder().token(settings.telegram_bot_api_token).build()
bot = application.bot

logger = logging.getLogger(__name__)


async def notify_telegram_chat(chat_id: int, text: str):
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


async def notify_cometa_telegram_channel(text: str):
    return await notify_telegram_chat(settings.telegram_channel_id, text)


def notify_discord_webhook(text: str):
    if settings.discord_notify_webhook_url is None:
        return
    webhook = DiscordWebhook(url=settings.discord_notify_webhook_url, content=text, embeds=[], attachments=[])
    _ = webhook.execute()


async def announce_stake(
        duration: timedelta,
        lock_duration: timedelta,
        metadata: dict
) -> None:
    stake_token_id = int(metadata['stake_token_id'])
    reward_token_id = int(metadata['reward_token_id'])

    stake_token = get_asset(stake_token_id)
    reward_token = get_asset(reward_token_id)

    stake_token_link = f'https://vestige.fi/asset/{stake_token_id}'
    reward_token_link = f'https://vestige.fi/asset/{reward_token_id}'

    stake_token_name = stake_token['params']['unit-name']
    reward_token_name = reward_token['params']['unit-name']
    token_buy_link = 'https://app.cometa.farm/swap'

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
        telegram_text = f'''
💸 New pool <a href="{stake_token_link}">{stake_token_name}</a> → <a href="{reward_token_link}">{reward_token_name}</a>

⏳ <b>{duration.days} days</b>
{lock_str}
✅ <a href="{token_buy_link}">Buy {stake_token_name}.</a>

Enjoy farming ❤️ 

https://app.cometa.farm/
        '''
        await notify_cometa_telegram_channel(telegram_text)
    except Exception as e:
        logger.exception(e)

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 **{lock_duration.days} days**\n'
        discord_text = f'''
💸 New pool **{stake_token_name} → {reward_token_name}**

⏳ **{duration.days} days**
{lock_str}
ℹ️ **${stake_token_name}** *{stake_token_link}*
ℹ️ **${reward_token_name}** *{reward_token_link}*

✅ Buy {stake_token_name}: *{token_buy_link}*

Enjoy staking ❤️ 

https://app.cometa.farm/
        '''
        notify_discord_webhook(discord_text)
    except Exception as e:
        logger.exception(e)


async def announce_farm(
        duration: timedelta,
        lock_duration: timedelta,
        metadata: dict
) -> None:
    if metadata.get('asset1_id') is None:
        return await announce_stake(duration, lock_duration, metadata)

    lp_token_id = int(metadata['stake_token_id'])
    asset1_id = int(metadata['asset1_id'])
    asset2_id = int(metadata['asset2_id'])
    reward_token_id = int(metadata['reward_token_id'])

    lp_token = get_asset(lp_token_id)
    asset1 = get_asset(asset1_id)
    asset2 = get_asset(asset2_id)
    reward_token = get_asset(reward_token_id)

    asset1_link = f'https://vestige.fi/asset/{asset1_id}'
    asset2_link = f'https://vestige.fi/asset/{asset2_id}'
    reward_link = f'https://vestige.fi/asset/{reward_token_id}'
    lp_pool_address = lp_token['params']['reserve']
    get_lp_link = f'https://app.tinyman.org/#/pool/{lp_pool_address}/add-liquidity'

    asset1_name = asset1['params']['unit-name']
    asset2_name = asset2['params']['unit-name']
    reward_token_name = reward_token['params']['unit-name']

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
        asset1_str = f'<a href="{asset1_link}">{asset1_name}</a>' if asset1_id != 0 else 'ALGO'
        asset2_str = f'<a href="{asset2_link}">{asset2_name}</a>' if asset2_id != 0 else 'ALGO'
        telegram_text = f'''
💸 New pool {asset1_str}/{asset2_str} → <a href="{reward_link}">{reward_token_name}</a>

⏳ <b>{duration.days} days</b>
{lock_str}
✅ <a href="{get_lp_link}">Get LP tokens.</a>

Enjoy farming ❤️ https://app.cometa.farm/
        '''
        await notify_cometa_telegram_channel(telegram_text)
    except Exception as e:
        logger.exception(e)

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 **{lock_duration.days} days**\n'
        assets_info_str = ''
        if asset1_id != 0:
            assets_info_str += f'ℹ️ **${asset1_name}** *{asset1_link}*\n'
        if asset2_id != 0:
            assets_info_str += f'ℹ️ **${asset2_name}** *{asset2_link}*\n'
        if reward_token_id != asset1_id and reward_token_id != asset2_id:
            assets_info_str += f'ℹ️ **${reward_token_name}** *{reward_link}*\n'
        discord_text = f'''
💸 New pool **{asset1_name}/{asset2_name} → {reward_token_name}**

⏳ **{duration.days} days**
{lock_str}
{assets_info_str}
✅ Get LP tokens: *{get_lp_link}*

Enjoy farming ❤️ https://app.cometa.farm/
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

    token_link = f'https://vestige.fi/asset/{stake_token_id}'
    token_buy_link = 'https://app.cometa.farm/swap'

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 <b>{lock_duration.days} days</b>\n'
        token_str = f'<a href="{token_link}">{stake_token_name}</a>'
        telegram_text = f'''
💸 New pool {token_str} → {token_str}

⏳ <b>{duration.days} days</b>
{lock_str}
✅ <a href="{token_buy_link}">Buy {stake_token_name}.</a>

Enjoy staking ❤️ https://app.cometa.farm/
    '''
        await notify_cometa_telegram_channel(telegram_text)
    except Exception as e:
        logger.exception(e)

    try:
        lock_str = '' if lock_duration.days == 0 else f'🔒 **{lock_duration.days} days**\n'
        discord_text = f'''
💸 New pool **{stake_token_name} → {stake_token_name}**

⏳ **{duration.days} days**
{lock_str}
ℹ️ **${stake_token_name}** *{token_link}*

✅ Buy {stake_token_name}: *{token_buy_link}*

Enjoy staking ❤️ 

https://app.cometa.farm/
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
    try:
        duration = duration_from_block_count(end_block - begin_block + 1)
        if lock_length_blocks != 0:
            lock_length_blocks += 2619  # epsilon to get more accurate number of days (10% of ~26181 blocks per day)
        lock_duration = duration_from_block_count(lock_length_blocks)

        if type == ContractType.FARM:
            return await announce_farm(duration, lock_duration, metadata)
        elif type == ContractType.DISTRIBUTION:
            return await announce_distribution(duration, lock_duration, metadata)
        else:
            raise Exception(f'Unknown contract type: {type}')
    except Exception as e:
        logger.exception(e)
