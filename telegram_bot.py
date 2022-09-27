import atexit
import logging
from typing import Optional

from algosdk.encoding import is_valid_address
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

from core.cometa import get_user_pools
from bot.context import app_context
from bot.db.model import CometaUser
from bot.db.users import create_user, get_user_by_tg
from bot.env import FEEDBACK_COMMAND, settings, SUPPORT_COMMAND
from bot.log import setup_logging
from bot.notifier import schedule_notifications
from bot.utils import seconds_format, usd_format

# TODO: move commands to separate files
from core.js_interop import start_js_interop_server


async def start(update: Update, context: CallbackContext):
    await update.message.reply_html(f'🤖 I\'m glad to see you, {update.message.from_user.name}, let\'s be friends!👀\n\n'
                                    'I will try to make your DeFi experience on Cometa as easy as possible😉\n\n'
                                    'Please register first with:\n'
                                    '<code>/register YOUR_ALGO_ADDRESS</code>\n\n'
                                    'To know all the cool stuff I can do use:\n'
                                    '/help')


async def check_registration(update: Update) -> Optional[CometaUser]:
    tg_user = update.message.from_user
    user = get_user_by_tg(tg_user.id)
    if user is None:
        await update.message.reply_html(f'🤖 Please register first with:\n'
                                        f'<code>/register YOUR_ALGO_ADDRESS</code>\n\n'
                                        f'To know more about me please use:\n'
                                        f'/help')
        return None
    return user


async def show_pools(update: Update, context: CallbackContext):
    user = await check_registration(update)
    if user is None:
        return

    pools = await get_user_pools(user.algo_address)
    if pools:
        reply_text = '🤖 <b>Your pools:</b>\n\n'

        for pool in pools:
            reply_text += '✅' if pool.ended_duration is None else '❌'  # TODO: facepalm
            reply_text += f' <b>{pool.name}</b>\n' \
                          f'Staked = <b>${usd_format(pool.staked_usd)}</b>, ' \
                          f'rewards = <b>${usd_format(pool.reward_usd)}</b>\n'
            if pool.ended_duration is not None:
                reply_text += f'<i>Withdraw ASAP! It ended {seconds_format(pool.ended_duration)} ago :(</i>\n'
            reply_text += '\n'

        reply_text += 'To manage your pools go to https://app.cometa.farm/'
    else:
        reply_text = '🤖 You don\'t have any pools, that\'s strange...' \
                     '\n\n' \
                     'Check out https://app.cometa.farm/ to get decent APRs with the best UX on Algorand😏'

    await update.message.reply_html(reply_text)


async def track_address(update: Update, context: CallbackContext):
    tg_user = update.message.from_user
    if not context.args:
        await update.message.reply_text('🤖 Please provide address!')
        return

    address = context.args[0]
    if not is_valid_address(address):
        await update.message.reply_text(f'🤖 Oh no... Please {tg_user.name}! Provide your Algorand address👆')
        return

    user = get_user_by_tg(tg_user.id)
    if user is None:
        user = create_user(address, tg_user.id, tg_user.id)
        new_user_msg = f'New #user {tg_user.name}!\nAlgo address {address}'
        await context.bot.send_message(settings.feedback_chat_id, new_user_msg)
    else:
        user.pools = {}
        user.algo_address = address

    await update.message.reply_html(f'🤖 Great, {tg_user.name}!\nTracking <code>{address}</code>.')
    await show_pools(update, context)


async def get_feedback(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text('🤖 Please provide the feedback!')
        return
    tg_user = update.message.from_user

    text_title = f'New #feedback from {tg_user.name}'
    logging.info(text_title)

    feedback_text = update.message.text_markdown[len(FEEDBACK_COMMAND) + 2:]
    feedback = f'{text_title}:\n\n{feedback_text}'
    await context.bot.send_message(settings.feedback_chat_id, feedback)

    await update.message.reply_text(f'🤖 Thank you, {tg_user.name}, your feedback is submitted!❤')


async def get_support(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text('🤖 Please describe your problem!')
        return
    tg_user = update.message.from_user

    text_title = f'New #ticket from {tg_user.name}'
    logging.info(text_title)

    support_text = update.message.text_markdown[len(SUPPORT_COMMAND) + 2:]
    support = f'{text_title}:\n\n{support_text}'
    await context.bot.send_message(settings.support_chat_id, support)

    await update.message.reply_text(f'🤖 Thank you, {tg_user.name}, one of our admins will contact you ASAP!❤')


# TODO: log new users to airtable
async def register(update: Update, context: CallbackContext):
    tg_user = update.message.from_user
    user = get_user_by_tg(tg_user.id)
    if user is not None:
        await update.message.reply_html(f'🤖 You are already registered!\n'
                                        f'For now I am tracking <code>{user.algo_address}</code> for you😉'
                                        f'To know more about me please use:\n'
                                        f'/help'
                                        )
        return

    logging.info(f'Registering {tg_user.name}.')

    await track_address(update, context)


async def change_address(update: Update, context: CallbackContext):
    if check_registration(update) is None:
        return

    await track_address(update, context)


async def show_help(update: Update, context: CallbackContext):
    text = f'🤖 Hello, {update.message.from_user.name}, it is a pleasure to assist you!☺️' \
           f'\n\n' \
           f'✅ I will remind you <b>to withdraw from ended pools</b>.' \
           f'\n\n' \
           f'✅ I will remind you <b>to compound</b> in pools where you farmed <b>more than 1% of your stake</b> ' \
           f'(to get decent APY).' \
           f'\n\n' \
           f'<i>I will notify only once per day. ' \
           f'Soon you will be able to manage the frequency as well as best compounding interest!</i>' \
           f'\n\n' \
           f'What else can I do?😏' \
           f'\n\n'\
           f'✏️To change the address to track:' \
           f'\n' \
           f'<code>/change_address NEW_ADDRESS</code>' \
           f'\n\n' \
           f'🚀To show your current Cometa pools:' \
           f'\n' \
           f'/my_pools' \
           f'\n\n' \
           f'💁‍♀️To share any feedback about Cometa:' \
           f'\n' \
           f'<code>/feedback YOUR_FEEDBACK</code>' \
           f'\n\n' \
           f'<b>🚨 If you have any problems with bot or Cometa</b>, please describe it and <b>our team will contact you ASAP</b>:' \
           f'\n' \
           f'<code>/support DESCRIPTION</code>' \
           f'\n\n' \
           f'<i>And don\'t forget to farm</i>😉\n\n' \
           f'https://app.cometa.farm/'

    await update.message.reply_html(text, disable_web_page_preview=True)


def start_bot():
    setup_logging()

    # TODO: implement Command class
    app_context.application.add_handler(CommandHandler('start', start))
    app_context.application.add_handler(CommandHandler('register', register))
    app_context.application.add_handler(CommandHandler('change_address', change_address))
    app_context.application.add_handler(CommandHandler('my_pools', show_pools))

    app_context.application.add_handler(CommandHandler(FEEDBACK_COMMAND, get_feedback))
    app_context.application.add_handler(CommandHandler(SUPPORT_COMMAND, get_support))

    app_context.application.add_handler(CommandHandler('help', show_help))

    schedule_notifications()

    app_context.application.run_polling()

    logging.info('Bot started!')


def tear_down():
    logging.info('EXIT BOT\n\nBye!\n')


if __name__ == '__main__':
    atexit.register(tear_down)

    try:
        with start_js_interop_server():
            start_bot()
    except Exception as ex:
        logging.exception(ex)
