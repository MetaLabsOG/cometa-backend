import atexit
import logging
from typing import Optional

from algosdk.encoding import is_valid_address
from telegram import Update, User
from telegram.ext import CallbackContext, CommandHandler

from bot.cometa import schedule_airtable_updates, get_user_pools
from bot.context import app_context
from bot.db.events import get_events
from bot.db.model import CometaUser
from bot.db.users import create_user, get_user_by_tg, update_user
from bot.env import FEEDBACK_COMMAND, settings, SUPPORT_COMMAND
from bot.log import setup_logging
from bot.notifier import schedule_notifications


# TODO: make commands async
# TODO: move commands to separate files

async def start(update: Update, context: CallbackContext):
    update.message.reply_html(f'I am glad to see you, {update.message.from_user.name}!\n'
                              'I will notify you to compound your rewards❤\n\n'
                              'Please register first with\n'
                              '<code>/register YOUR_ALGO_ADDRESS</code>')


async def check_registration(update: Update) -> Optional[CometaUser]:
    tg_user = update.message.from_user
    user = get_user_by_tg(tg_user.id)
    if user is None:
        update.message.reply_text(f'Please register first.')
        return None
    return user


async def track_address(update: Update, context: CallbackContext):
    tg_user = update.message.from_user
    if not context.args:
        update.message.reply_text('Please provide address!')
        return

    address = context.args[0]
    if not is_valid_address(address):
        update.message.reply_text(f'Oh no... Please {tg_user.name}! Provide your Algorand address👆')
        return

    user_events = get_events({'address': address})

    user = get_user_by_tg(tg_user.id)
    if user is None:
        user = create_user(address, tg_user.id, tg_user.id)
    else:
        user.pools = {}
        user.algo_address = address

    for e in user_events:
        # time in ascending order
        user.update(e)
    update_user(user)
    print(f'Recorded {len(user_events)} old events.')

    update.message.reply_html(f'Great, {tg_user.name}!\nTracking <code>{address}</code>.')


async def show_pools(update: Update, context: CallbackContext):
    user = check_registration(update)
    if user is None:
        return

    pools = await get_user_pools(user.algo_address)
    reply_text = 'Your pools:\n\n'
    for pool in pools:
        reply_text += f'<b>{pool.name}</b>\n' \
                      f'Staked: ${pool.staked_usd}\n'
        if pool.ended_duration is not None:
            reply_text += f'It ended {pool.ended_duration}s ago :('
        reply_text += '\n'

    update.message.reply_html(reply_text)


async def get_feedback(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text('Please provide the feedback!')
        return
    tg_user = update.message.from_user

    text_title = f'New feedback from {tg_user.name}'
    logging.info(text_title)

    feedback_text = update.message.text_markdown[len(FEEDBACK_COMMAND) + 2:]
    feedback = f'{text_title}:\n\n{feedback_text}'
    context.bot.send_message(settings.feedback_chat_id, feedback)

    update.message.reply_text(f'Thank you, {tg_user.name}, your feedback is submitted!❤')


async def get_support(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text('Please describe your problem!')
        return
    tg_user = update.message.from_user

    text_title = f'New ticket from {tg_user.name}'
    logging.info(text_title)

    support_text = update.message.text_markdown[len(SUPPORT_COMMAND) + 2:]
    support = f'{text_title}:\n\n{support_text}'
    context.bot.send_message(settings.support_chat_id, support)

    update.message.reply_text(f'Thank you, {tg_user.name}, one of our admins will contact you ASAP!❤')


# TODO: log new users to airtable
async def register(update: Update, context: CallbackContext):
    tg_user = update.message.from_user
    user = get_user_by_tg(tg_user.id)
    if user is not None:
        update.message.reply_html(f'You are already registered!\n'
                                  f'My apologies, I am too young, I can track only one address. But I will learn soon😏\n'
                                  f'\nFor now I am tracking <code>{user.algo_address}</code> for you.')
        return

    print(f'Registering {tg_user.name}.')

    await track_address(update, context)


async def change_address(update: Update, context: CallbackContext):
    if check_registration(update) is None:
        return

    track_address(update, context)


async def show_help(update: Update, context: CallbackContext):
    text = f'Hello, {update.message.from_user.name}, it is a pleasure to assist you!' \
           f'\n\n' \
           f'To change the address to track:\n' \
           f'<code>/change_address NEW_ADDRESS</code>' \
           f'\n\n' \
           f'To share any feedback about Cometa:\n' \
           f'<code>/feedback YOUR_FEEDBACK</code>' \
           f'\n\n' \
           f'If you have any problems, describe it and <b>our team will contact you ASAP</b>:\n' \
           f'<code>/support DESCRIPTION</code>'

    update.message.reply_html(text, disable_web_page_preview=True)


def start_bot():
    setup_logging()

    # TODO: implement Command class
    app_context.updater.dispatcher.add_handler(CommandHandler('start', start))
    app_context.updater.dispatcher.add_handler(CommandHandler('register', register))
    app_context.updater.dispatcher.add_handler(CommandHandler('change_address', change_address))
    app_context.updater.dispatcher.add_handler(CommandHandler('my_pools', show_pools))

    app_context.updater.dispatcher.add_handler(CommandHandler(FEEDBACK_COMMAND, get_feedback))
    app_context.updater.dispatcher.add_handler(CommandHandler(SUPPORT_COMMAND, get_support))

    app_context.updater.dispatcher.add_handler(CommandHandler('help', show_help))

    schedule_airtable_updates()
    schedule_notifications()

    app_context.updater.start_polling()

    print('Bot started!')


def tear_down():
    logging.info('EXIT BOT\n\nBye!\n')


if __name__ == '__main__':
    atexit.register(tear_down)

    try:
        start_bot()
    except Exception as ex:
        logging.exception(ex)
