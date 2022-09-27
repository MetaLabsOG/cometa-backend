import logging

from core.constants import LOG_FORMAT, LOG_DATE_FORMAT

LOGGING_LEVEL = logging.DEBUG
TELEGRAM_API_LOGGING_LEVEL = logging.INFO


def setup_logging():
    logging.basicConfig(
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=LOGGING_LEVEL
    )

    logging.getLogger('telegram').setLevel(TELEGRAM_API_LOGGING_LEVEL)
    logging.getLogger('JobQueue').setLevel(TELEGRAM_API_LOGGING_LEVEL)

    logging.getLogger('telegram.ext.dispatcher').setLevel(LOGGING_LEVEL)
