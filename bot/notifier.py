import time
from datetime import datetime
from threading import Thread
from typing import Dict

from telegram import ParseMode

from bot.context import app_context
from bot.db import users
from bot.db.model import PoolInfo, CometaUser
from bot.env import MONITOR_LOG_DELAY
from bot.utils import td_format


def pool_info(info: PoolInfo):
    # TODO: calculate pool APY and show
    return f'<b>{info.name}</b> was claimed <b>{td_format(info.no_interact_for)}</b> ago :(\n' \
           f'<i>You could be so rich...</i>\nAnd you still may be! Just compound ;)'


def notify_user(user: CometaUser, pools: Dict[str, PoolInfo]):
    text = f'Hey, beautiful!❤️\n'
    text += f'What about some compounding?😏\n'
    text += '\n'
    text += '\n\n'.join(pool_info(info) for asa_id, info in pools.items())
    text += '\n\nIt is the time.\nhttps://app.testnet.cometa.farm/'
    text += '\n\n<i>(soon I will be showing your APY ;)</i>'

    # TODO: save all notifications to DB
    print(text)

    app_context.bot.send_message(text=text, chat_id=user.telegram_chat_id, parse_mode=ParseMode.HTML)
    user.last_reminded = int(time.time())
    users.update_user(user)


def monitor_and_notify_all():
    iterations = 0
    prev_log_time = datetime.utcnow()
    while True:
        all_users = users.get_users({})

        for user in all_users:
            if not user.should_remind():
                continue

            user_notifications = {}

            for lp_asa_id, info in user.pools.items():
                if info.should_remind():
                    user_notifications[lp_asa_id] = info
                    continue  # iterating user pools

            if not user_notifications:
                continue  # iterating users

            notify_user(user, user_notifications)

        iterations += 1
        time.sleep(1)

        now = datetime.utcnow()
        if now - prev_log_time > MONITOR_LOG_DELAY:
            print(f'Monitoring all the time. {iterations} iterations since start.')
            prev_log_time = now


def schedule_notifications():
    # TODO: use executor
    daemon = Thread(target=monitor_and_notify_all, args=(), daemon=True, name='Notifier')
    daemon.start()

