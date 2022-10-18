from dataclasses import dataclass
from functools import cached_property

from telegram import Bot
from telegram.ext import Application

from bot.env import bot_settings


@dataclass
class Context:
    @cached_property
    def application(self) -> Application:
        return Application.builder().token(bot_settings.telegram_api_token).build()

    @cached_property
    def bot(self) -> Bot:
        return self.application.bot


app_context = Context()
