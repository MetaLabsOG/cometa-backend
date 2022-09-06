import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

LOGGING_LEVEL = logging.DEBUG
TELEGRAM_API_LOGGING_LEVEL = logging.INFO

LOGS_DIR = f'/srv/logs/cometa-bot'


def setup_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)
    # 10000 here means infinity
    rotating_file_handler = TimedRotatingFileHandler(f'{LOGS_DIR}/bot.log', backupCount=10000, when='D', interval=1)
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
