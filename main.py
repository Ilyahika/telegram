"""Точка входа QWE: FastAPI + (по настройке) Telegram polling."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from crash_live import room
from auth import verify_init_data
from bot import run_bot
from database import initialize, upsert_player, claim_bonus, connection, bank_operation, admin_settings

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
    crash_task = asyncio.create_task(room.run())
    yield
    crash_task.cancel()
    with suppress(asyncio.CancelledError):
        await crash_task
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


@app.websocket("/ws/crash")
async def crash_socket(websocket: WebSocket):
    """Общая трансляция Crash для всех клиентов без денежных ставок."""
    await room.connect(websocket)


@app.get("/api/crash/state")
def crash_state():
    """Резервная точка получения текущего состояния игры."""
    return room.snapshot()


class BankRequest(TelegramLogin):
    action: str
    amount: int = Field(default=0, ge=0, le=1000000)

@app.post("/api/bank")
def bank(payload: BankRequest):
    """Виртуальный банк: проверка Telegram и сумма только на стороне сервера."""
    user = verify_init_data(payload.init_data)
    return bank_operation(int(user["id"]), payload.action, payload.amount)

class AdminRateRequest(TelegramLogin):
    target_id: int
    rate: float

@app.post("/api/admin/bank-rate")
def set_bank_rate(payload: AdminRateRequest):
    """Изменять виртуальную ставку может только владелец панели."""
    user = verify_init_data(payload.init_data)
    return admin_settings(int(user["id"]), payload.target_id, payload.rate)

# Публичные котировки для ознакомления, без покупки настоящей криптовалюты.
_market_cache = {"fetched":0, "data": None}
@app.get("/api/market/btc")
def bitcoin_quote():
    import json, time, urllib.request
    now=time.time()
    if _market_cache["data"] and now-_market_cache["fetched"]<90:
        return _market_cache["data"]
    url="https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub&include_24hr_change=true&include_last_updated_at=true"
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"QWE-Educational-Market/0.4","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=5) as response:
            data=json.load(response)["bitcoin"]
        result={"price_rub":data["rub"], "change_24h":data.get("rub_24h_change"),"as_of":data.get("last_updated_at",int(now)),"source":"CoinGecko", "stale":False}
        _market_cache.update(fetched=now,data=result)
        return result
    except Exception:
        if _market_cache["data"]: return {**_market_cache["data"],"stale":True}
        return {"price_rub":None,"change_24h":None,"source":"CoinGecko", "stale":True,"error":"Котировка временно недоступна"}
