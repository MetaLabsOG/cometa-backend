import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from bot.env import settings

LOGGING_LEVEL = logging.DEBUG
TELEGRAM_API_LOGGING_LEVEL = logging.INFO


def setup_logging():
    os.makedirs(settings.logs_dir, exist_ok=True)
    # 10000 here means infinity
    rotating_file_handler = TimedRotatingFileHandler(f'{settings.logs_dir}/bot.log', backupCount=10000, when='D', interval=1)
    console_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        format='[%(asctime)s][%(levelname)s] %(message)s',
        datefmt='%I:%M:%S',
        level=LOGGING_LEVEL,
        **{'handlers': [console_handler, rotating_file_handler]}
    )

    logging.getLogger('telegram').setLevel(TELEGRAM_API_LOGGING_LEVEL)
    logging.getLogger('JobQueue').setLevel(TELEGRAM_API_LOGGING_LEVEL)

    logging.getLogger('telegram.ext.dispatcher').setLevel(LOGGING_LEVEL)
