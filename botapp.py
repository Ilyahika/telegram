"""
botapp.py — Telegram-бот (aiogram).

Бот работает в фоне и НЕ блокирует запуск сайта. Раньше сервер ждал ответа Telegram (getMe,
deleteWebhook — до 60 секунд каждый) ещё до того, как начинал принимать запросы: отсюда
долгая загрузка Mini App после «засыпания» Render.
"""
import asyncio
import logging
from types import SimpleNamespace
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import CommandStart
from aiogram.types import PreCheckoutQuery, LabeledPrice
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config import BOT_TOKEN, WEBAPP_URL

log = logging.getLogger('miniapp.bot')
dp = Dispatcher()  # диспетчер: раздаёт входящие сообщения обработчикам ниже

# Общее состояние бота (читает /health и админ-панель)
state = SimpleNamespace(bot=None, username='', polling=False, error='')


# Функция create_bot: см. параметры, описание и вызовы ниже.
def create_bot() -> Optional[Bot]:
    """Создаёт объект бота. Возвращает None, если токен не задан или имеет неверный формат."""
    if not BOT_TOKEN:
        state.error = 'BOT_TOKEN не задан'
        return None
    try:
        return Bot(token=BOT_TOKEN)
    except Exception as exc:  # aiogram проверяет формат токена при создании
        state.error = f'BOT_TOKEN имеет неверный формат ({type(exc).__name__})'
        return None


# Функция cmd_start: см. параметры, описание и вызовы ниже.
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Команда /start — отправляет кнопку, открывающую Mini App."""
    # Telegram deep links /start ref_<inviter> are processed only for newly created accounts.
    args=(message.text or '').split(maxsplit=1)
    if len(args)==2 and args[1].startswith('ref_'):
        try:
            inviter=int(args[1][4:]); uid=message.from_user.id
            if inviter!=uid:
                import time
                from db import session
                from v14 import config
                with session(write=True) as db:
                    now=int(time.time())
                    db.execute('INSERT OR IGNORE INTO players(telegram_id,telegram_name,created_at) VALUES(?,?,?)',(uid,message.from_user.first_name or 'Игрок',now))
                    db.execute('INSERT OR IGNORE INTO bh(telegram_id,last_claim,energy_ts) VALUES(?,?,?)',(uid,now,now))
                    target=db.execute('SELECT 1 FROM players WHERE telegram_id=?',(inviter,)).fetchone()
                    user_row=db.execute('SELECT created_at FROM players WHERE telegram_id=?',(uid,)).fetchone()
                    if target and now-user_row[0]<=900:
                        result=db.execute('INSERT OR IGNORE INTO viva_referrals VALUES (?,?,?)',(uid,inviter,now))
                        if result.rowcount:
                            db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(int(config(db,'ref_inviter')),inviter))
                            db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(int(config(db,'ref_invited')),uid))
        except (ValueError,TypeError):pass
    if not WEBAPP_URL.startswith('https://'):
        await message.answer('⚠️ Администратор ещё не указал WEBAPP_URL.')
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🚀 Открыть', web_app=WebAppInfo(url=WEBAPP_URL))]])
    await message.answer('🎣 Viva — рыбацкий клуб. Нажми кнопку, чтобы открыть приложение!', reply_markup=keyboard)


# Функция checkout: см. параметры, описание и вызовы ниже.
@dp.pre_checkout_query()
async def checkout(query: PreCheckoutQuery):
    import re
    match=re.fullmatch(r'viva_(50|100|250|500)_([0-9]+)_[0-9a-f]{16}',query.invoice_payload or '')
    valid=bool(match and query.currency=='XTR' and query.total_amount==int(match[1]) and int(match[2])==query.from_user.id)
    await query.answer(ok=valid,error_message=None if valid else 'Некорректный платёж')

# Функция paid: см. параметры, описание и вызовы ниже.
@dp.message(lambda message: message.successful_payment is not None)
async def paid(message: Message):
    import re
    payment=message.successful_payment
    match=re.fullmatch(r'viva_(50|100|250|500)_([0-9]+)_[0-9a-f]{16}',payment.invoice_payload or '')
    if not match or int(match[2])!=message.from_user.id or payment.currency!='XTR' or payment.total_amount!=int(match[1]):return
    from v14 import credit_payment
    if credit_payment(message.from_user.id,int(match[1]),payment.telegram_payment_charge_id):
        await message.answer(f'✅ Баланс Viva Shop пополнен на {match[1]} ⭐')


# Функция run_bot: см. параметры, описание и вызовы ниже.
async def run_bot(bot: Bot) -> None:
    """Фоновая задача: проверяет токен, сбрасывает вебхук и запускает long polling."""
    attempt = 0
    while True:
        try:
            me = await bot.get_me()                 # узнаём @username бота (нужен для подсказок об ошибках)
            state.username, state.error = me.username or str(me.id), ''
            log.info('Бот авторизован: @%s', state.username)
            break
        except TelegramUnauthorizedError:           # токен неверный — повторять бессмысленно
            state.error = 'BOT_TOKEN неверный или отозван: возьми новый в @BotFather'
            log.error(state.error)
            return
        except Exception:                           # сеть/таймаут — пробуем снова с растущей паузой
            attempt += 1
            delay = min(60, 2 ** attempt)
            log.warning('getMe не удался (попытка %d), повтор через %d с', attempt, delay)
            await asyncio.sleep(delay)

    try:
        await bot.delete_webhook(drop_pending_updates=True)  # polling и webhook одновременно не работают
    except Exception:
        log.exception('delete_webhook не удался')

    state.polling = True
    try:
        await dp.start_polling(bot, handle_signals=False)    # handle_signals=False: сигналы обрабатывает uvicorn
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state.error = f'Polling остановился: {type(exc).__name__}'
        log.exception('Polling упал')
    finally:
        state.polling = False

from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from config import ADMIN_ID

# Функция admin_backup: см. параметры, описание и вызовы ниже.
@dp.message(Command('backup'))
async def admin_backup(message: Message):
    if message.from_user.id != ADMIN_ID:return
    import sqlite3,tempfile
    from pathlib import Path
    from config import DB_PATH
    with tempfile.NamedTemporaryFile(suffix='.db') as f:
        conn=sqlite3.connect(str(DB_PATH));target=sqlite3.connect(f.name)
        try:conn.backup(target)
        finally:target.close();conn.close()
        await message.answer_document(BufferedInputFile(Path(f.name).read_bytes(),filename='viva-backup.db'),caption='Резервная копия Viva. Храни файл в безопасном месте.')

# Функция admin_restore_document: см. параметры, описание и вызовы ниже.
@dp.message(lambda message: message.document is not None)
async def admin_restore_document(message: Message):
    if message.from_user.id != ADMIN_ID:return
    doc=message.document
    if not doc.file_name.lower().endswith(('.db','.sqlite','.sqlite3')) or doc.file_size>100*1024*1024:
        await message.answer('Пришли SQLite базу .db до 100 МБ');return
    import io,sqlite3,os,tempfile
    from pathlib import Path
    from config import DB_PATH
    buff=io.BytesIO();await message.bot.download(doc,destination=buff);blob=buff.getvalue()
    if not blob.startswith(b'SQLite format 3\x00'):
        await message.answer('Ошибка: это не база SQLite');return
    with tempfile.NamedTemporaryFile(dir=DB_PATH.parent,delete=False) as f:f.write(blob);path=f.name
    try:
        conn=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
        try:
            valid=conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:conn.close()
        if not valid or not {'players','bh','fishing_progress','fishing_gear'}<=tables:
            await message.answer('База повреждена или несовместима');return
        os.replace(path,DB_PATH.with_suffix('.restore-pending.db'))
        await message.answer('✅ Файл проверен и сохранён как restore-pending.db. Восстанавливать следует на остановленном сервере, чтобы не повредить живую базу. Текущие данные не изменены.')
    finally:Path(path).unlink(missing_ok=True)
