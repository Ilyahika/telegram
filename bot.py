import os 
import asyncio
from database import register_user, init_database
import logging

from aiogram import Dispatcher, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo
)
from dotenv import load_dotenv
load_dotenv()

Token = os.getenv("BOT_TOKEN")
Webapp_url = os.getenv("WEBAPP_URL")

dp = Dispatcher()

@dp.message()
async def message(message: Message):
    message1 = message.from_user
    user_id = message.from_user.id

    if message1 is None:
        return 
    player = register_user(
        user_id=user_id
    )

    await message.answer(f"""
🤵 Привет {player['username']}! 
~ Это игровой бот, для активации нажми на кнопку ниже
""")


async def main():

    # Включаем вывод информации о работе бота
    logging.basicConfig(level=logging.INFO)

    # Проверяем наличие токена
    if not Token:
        raise RuntimeError("BOT_TOKEN не найден в .env")

    # Создаём таблицы базы данных
    init_database()

    # Создаём экземпляр бота
    bot = Bot(token=Token)

    try:
        # Удаляем webhook, если он был установлен ранее
        await bot.delete_webhook(drop_pending_updates=False)

        # Начинаем получать сообщения от Telegram
        await dp.start_polling(bot)

    finally:
        # Закрываем соединение с Telegram
        await bot.session.close()


# Точка входа в программу
if __name__ == "__main__":
    asyncio.run(main())
