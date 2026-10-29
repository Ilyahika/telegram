"""Точка входа QWE: FastAPI + (по настройке) Telegram polling."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import verify_init_data
from bot import run_bot
from database import initialize, upsert_player, claim_bonus, connection

load_dotenv()
logging.basicConfig(level=logging.INFO)
ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Создаём таблицу при запуске, корректно останавливаем фоновый polling."""
    initialize()
    bot_task = None
    if os.getenv("RUN_BOT", "1") == "1":
        bot_task = asyncio.create_task(run_bot())
    yield
    if bot_task is not None:
        bot_task.cancel()
        with suppress(asyncio.CancelledError):
            await bot_task


app = FastAPI(title="QWE Mini App", lifespan=lifespan)
# Статические CSS/JS доступны из /static/...
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


class TelegramLogin(BaseModel):
    # Проверяем длину запросов, чтобы не принимать чрезмерно большие данные
    init_data: str = Field(min_length=1, max_length=16384)


@app.get("/", include_in_schema=False)
def home():
    """Отдаём фронтенд пользователю Telegram."""
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/health")
def health():
    """Простая проверка, что сервер работает."""
    return {"status": "ok", "project": "QWE"}


@app.post("/api/auth")
def login(payload: TelegramLogin):
    """Только сервер проверяет подпись и создаёт/загружает профиль игрока."""
    verified_user = verify_init_data(payload.init_data)
    profile = upsert_player(verified_user)
    return {"success": True, "player": profile}


class BonusRequest(TelegramLogin):
    kind: str


@app.post("/api/bonus")
def get_bonus(payload: BonusRequest):
    """Важно: нельзя доверять ID игрока из браузера — проверяем подпись заново."""
    user = verify_init_data(payload.init_data)
    return claim_bonus(int(user["id"]), payload.kind)


@app.post("/api/admin/status")
def admin_status(payload: TelegramLogin):
    """Доступ к административной информации проверяется на сервере."""
    user = verify_init_data(payload.init_data)
    if int(user["id"]) != 1181838335:
        from fastapi import HTTPException
        raise HTTPException(403, "Доступ запрещён")
    db = connection()
    try:
        count = db.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        return {"players_count": count, "message": "Панель администратора QWE"}
    finally:
        db.close()
