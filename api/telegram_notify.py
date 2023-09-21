from datetime import timedelta
from typing import Optional

from telegram.constants import ParseMode
from telegram.ext import Application

from api.db_model import ContractType
from env import settings

application = Application.builder().token(settings.telegram_bot_api_token).build()
bot = application.bot

async def notify_chat(chat_id: int, text: str):
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML
    )


async def notify_cometa_channel(text: str):
    return await notify_chat(settings.telegram_channel_id, text)


def duration_from_blocks(blocks: int) -> timedelta:
    length_seconds = blocks * settings.block_time
    return timedelta(seconds=length_seconds)


async def notify_new_pool(
        description: str,
        begin_block: int,
        end_block: int,
        lock_length_blocks: int,
        type: ContractType,
        metadata: Optional[dict] = None,
        reward_token_id: Optional[int] = None,
        reward_amount: Optional[int] = None,
        algo_reward_amount: int = 0,
):
    length_blocks = end_block - begin_block + 1
    duration = duration_from_blocks(length_blocks)

    # TODO: add details, vestige links, projected APR (for 1000$)
    # if type == ContractType.FARM:
    #     dex = metadata['dex']
    #     asset_1_id = metadata['asset_1_id']
    #     asset_2_id = metadata['asset_2_id']
    # elif type == ContractType.DISTRIBUTION:
    #     pass

    lock_str = '' if lock_length_blocks == 0 else f'🔒 <b>{duration_from_blocks(lock_length_blocks).days}</b>\n'
    text = f'''
💥 New pool on Cometa!

💸 <b>{description}</b>

⏳ <b>{duration.days} days</b>
{lock_str}


<i>Don't miss it and enjoy farming!</i> ❤️

☄️ https://app.cometa.farm/
    '''

    return await notify_cometa_channel(text)
