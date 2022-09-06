from dataclasses import dataclass
from functools import cached_property

from telegram import Bot
from telegram.ext import Updater

from bot.env import settings


@dataclass
class Context:
    @cached_property
    def updater(self) -> Updater:
        return Updater(settings.telegram_api_token, use_context=True)

    @cached_property
    def bot(self) -> Bot:
        return self.updater.bot


app_context = Context()
