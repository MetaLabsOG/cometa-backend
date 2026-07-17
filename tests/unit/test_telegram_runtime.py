import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import Application


def test_telegram_entrypoints_import_with_locked_runtime() -> None:
    import telegram_bot
    from api import notifications
    from bot.context import Context

    assert callable(telegram_bot.start_bot)
    assert isinstance(notifications.application, Application)
    assert isinstance(Context().application, Application)


def test_message_all_rejects_non_admin_before_reading_recipients(monkeypatch) -> None:
    import telegram_bot

    reply_text = AsyncMock()
    update = SimpleNamespace(
        message=SimpleNamespace(
            from_user=SimpleNamespace(id=7),
            reply_text=reply_text,
        ),
    )
    context = SimpleNamespace(args=["hello"])
    monkeypatch.setattr(telegram_bot.bot_settings, "telegram_admin_ids", [42])

    asyncio.run(telegram_bot.message_all(update, context))

    reply_text.assert_awaited_once_with(
        "🤖 This command is restricted to administrators.",
    )


def test_change_address_awaits_registration_guard(monkeypatch) -> None:
    import telegram_bot

    check_registration = AsyncMock(return_value=None)
    track_address = AsyncMock()
    update = SimpleNamespace()
    context = SimpleNamespace()
    monkeypatch.setattr(telegram_bot, "check_registration", check_registration)
    monkeypatch.setattr(telegram_bot, "track_address", track_address)

    asyncio.run(telegram_bot.change_address(update, context))

    check_registration.assert_awaited_once_with(update)
    track_address.assert_not_awaited()
