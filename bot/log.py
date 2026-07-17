import logging

LOGGING_LEVEL = logging.DEBUG
TELEGRAM_API_LOGGING_LEVEL = logging.INFO
LOG_FORMAT = "[%(asctime)s][%(levelname)s][%(filename)s] %(message)s"
LOG_DATE_FORMAT = "%I:%M:%S"


def setup_logging():
    logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, level=LOGGING_LEVEL)

    logging.getLogger("telegram").setLevel(TELEGRAM_API_LOGGING_LEVEL)
    logging.getLogger("JobQueue").setLevel(TELEGRAM_API_LOGGING_LEVEL)

    logging.getLogger("telegram.ext.dispatcher").setLevel(LOGGING_LEVEL)
