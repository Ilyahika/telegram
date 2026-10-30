"""
main.py — точка входа. Запуск:  uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1

Что здесь происходит:
  1. при старте создаётся БД (мгновенно) и в ФОНЕ запускается Telegram-бот;
  2. подключаются маршруты: рыбалка и админ-панель;
  3. отдаются файлы интерфейса: index.html, единый style.css и app.js.
Важно: --workers 1, иначе несколько копий бота будут конфликтовать при polling.
"""
import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response

import admin
import botapp
import fishing
import community
import features_v11
import v14
from config import BOT_TOKEN, CORS_ORIGINS, ROOT, VERSION, WEBAPP_URL
from db import init_db, session, checkpoint_db
from auth import signed_user, register
from config import ADMIN_ID
from system_state import maintenance_state

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('miniapp')


# Функция lifespan: см. параметры, описание и вызовы ниже.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт: готовим БД и запускаем бота в фоне. Остановка: аккуратно гасим бота."""
    if not BOT_TOKEN:
        log.error('BOT_TOKEN не задан (Render -> Environment): API работать не будет')
    if not WEBAPP_URL.startswith('https://'):
        log.error('WEBAPP_URL не задан или не https: кнопка «Открыть» в боте не заработает')
    try:
        init_db()                                    # создаёт таблицы за миллисекунды
    except Exception:                                # сервер всё равно запускается: /health/db покажет проблему
        log.exception('База недоступна: запуск остановлен')
        raise
    bot = botapp.create_bot()
    botapp.state.bot = bot
    task = asyncio.create_task(botapp.run_bot(bot)) if bot else None   # бот стартует параллельно, сайт уже отвечает
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if bot:
            await bot.session.close()
        try:
            checkpoint_db()
        except Exception:
            log.exception('Не удалось объединить WAL; подтверждённые изменения остаются в журнале SQLite')


# docs/openapi отключены: схема API не должна быть публичной
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000)                      # сжимает ответы -> быстрее на мобильном интернете
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=['GET', 'POST'],
                   allow_headers=['Content-Type', 'X-Telegram-Init-Data'],
                   max_age=86400)                                          # браузер запоминает preflight на сутки

# --------------------------------------------------------------------- служебные маршруты
@app.get('/health')
def health():
    """Проверка «сервер жив». Не требует авторизации и не трогает БД — именно им клиент «будит» Render."""
    return {'status': 'ok', 'api': 'reachable', 'version': VERSION, 'time': int(time.time()), 'bot': botapp.state.username or None, 'polling': botapp.state.polling}


# Функция health_db: см. параметры, описание и вызовы ниже.
@app.get('/health/db')
def health_db():
    """Проверка доступности БД."""
    try:
        with session() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {'database': 'connected', 'tables_ready': {'players', 'bh', 'cars', 'mines2', 'fishing_progress', 'fishing_fish', 'fishing_finds', 'fishing_gear', 'fishing_cases', 'fishing_discovered'} <= tables}
    except Exception:
        log.exception('Проверка БД не прошла')
        raise HTTPException(503, 'SQLite недоступна; смотри Logs в Render')




# Функция system_status: см. параметры, описание и вызовы ниже.
@app.get('/api/system/status')
def system_status(user: dict = Depends(signed_user)):
    """Heartbeat and maintenance state for Telegram clients, including blocked players.

    Returns only public maintenance data. Admin identity is determined from signed initData.
    """
    state = maintenance_state()
    is_admin = user['id'] == ADMIN_ID
    if not state['enabled'] or is_admin:
        register(user)  # refresh last_seen at most once per 30 seconds
    return {**state, 'is_admin': is_admin, 'heartbeat_seconds': 10}

# --------------------------------------------------------------------- API
app.include_router(features_v11.router)
app.include_router(v14.router)
app.include_router(community.router)
app.include_router(fishing.router)      # рыбалка, снасти, инвентарь и кейсы
app.include_router(admin.router)        # админ-панель

# --------------------------------------------------------------------- интерфейс
# Отдаём только перечисленные файлы — исходники сервера (main.py и т.д.) не выставляются наружу
STATIC = {'style.css': 'text/css', 'app.js': 'application/javascript', 'viva2.css': 'text/css'}
# no-cache = «всегда сверяйся с сервером»; благодаря ETag неизменный файл отдаётся как 304 без тела
NO_CACHE = {'Cache-Control': 'no-cache'}


# Функция index: см. параметры, описание и вызовы ниже.
@app.get('/')
def index():
    """Главная страница Mini App."""
    return FileResponse(ROOT / 'index.html', media_type='text/html', headers=NO_CACHE)


# Функция favicon: см. параметры, описание и вызовы ниже.
@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    """Иконки нет — отвечаем пусто, чтобы не было 404 в логах."""
    return Response(status_code=204)


# Функция asset: см. параметры, описание и вызовы ниже.
@app.get('/assets/{name}')
def asset(name:str):
    if not __import__('re').fullmatch(r'emoji-[a-f0-9-]{1,80}\.svg',name) and not (__import__('re').fullmatch(r'fish12_(?:0[0-9]|1[0-9])\.webp',name)) and name not in {'lure_atlas.png'}:raise HTTPException(404,'Not found')
    path=ROOT/'assets'/name
    if not path.is_file():raise HTTPException(404,'Not found')
    return FileResponse(path,headers={'Cache-Control':'public, max-age=86400'})

# Функция static_file: см. параметры, описание и вызовы ниже.
@app.get('/{name}')
def static_file(name: str):
    """Статические файлы интерфейса (этот маршрут объявлен последним, чтобы не перекрывать остальные)."""
    if name not in STATIC:
        raise HTTPException(404, 'Not found')
    return FileResponse(ROOT / name, media_type=STATIC[name], headers=NO_CACHE)
