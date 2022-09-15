from dataclasses import dataclass
from functools import cached_property

from telegram import Bot
from telegram.ext import Updater, Application

from bot.env import settings


@dataclass
class Context:
    @cached_property
    def application(self) -> Application:
        return Application.builder().token(settings.telegram_api_token).build()

    @cached_property
    def bot(self) -> Bot:
        return self.application.bot


app_context = Context()
