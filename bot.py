"""Telegram-бот QWE (aiogram 3). Запускается из main.py вместе с FastAPI."""
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from database import upsert_player

logger = logging.getLogger(__name__)
dp = Dispatcher()


def mini_app_keyboard() -> InlineKeyboardMarkup:
    """Кнопка под сообщением в личном чате запускает Mini App."""
    url = os.getenv("WEBAPP_URL", "").rstrip("/")
    if not url.startswith("https://"):
        raise RuntimeError("WEBAPP_URL должен быть публичным HTTPS-адресом")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✦ Открыть QWE", web_app=WebAppInfo(url=url))
    ]])


@dp.message(CommandStart())
async def start(message: Message):
    """Обрабатываем /start и автоматически создаём профиль."""
    if message.chat.type != "private" or message.from_user is None:
        return
    player = upsert_player(message.from_user.model_dump(exclude_none=True))
    await message.answer(
        f"✦ Добро пожаловать в QWE, {player['display_name']}!\n\n"
        "Технические работы ещё идут. Открой приложение, чтобы увидеть стартовый экран.",
        reply_markup=mini_app_keyboard(),
    )


@dp.message()
async def any_message(message: Message):
    """При первом ЛЮБОМ сообщении в личке регистрируем игрока."""
    if message.chat.type != "private" or message.from_user is None:
        return
    player = upsert_player(message.from_user.model_dump(exclude_none=True))
    await message.answer(
        f"✦ QWE · {player['display_name']}\nТехнические работы продолжаются.",
        reply_markup=mini_app_keyboard(),
    )


async def run_bot():
    """Запуск polling. Нужен ровно ОДИН процесс бота."""
    token = os.getenv("BOT_TOKEN", "")
    if not token or token == "PASTE_YOUR_BOT_TOKEN":
        logger.warning("BOT_TOKEN не настроен — Telegram-бот не запущен")
        return
    bot = Bot(token=token)
    try:
        # Удаляем старый webhook, чтобы polling мог получать сообщения
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=False)
    finally:
        await bot.session.close()
