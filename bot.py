"""Telegram bot launching Mini App. Run as a separate process from FastAPI."""
import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

async def main():
    token=os.getenv('BOT_TOKEN','')
    url=os.getenv('WEBAPP_URL','')
    if not token or not url.startswith('https://'):
        raise RuntimeError('Укажи BOT_TOKEN и публичный HTTPS WEBAPP_URL')
    bot=Bot(token=token)
    dp=Dispatcher()
    @dp.message(CommandStart())
    async def start(message:Message):
        keyboard=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='🏝 Открыть Monster Islands',web_app=WebAppInfo(url=url))
        ]])
        await message.answer('🐲 Добро пожаловать в Monster Islands! Исследуй остров и собирай монстров.',reply_markup=keyboard)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__=='__main__':
    asyncio.run(main())
