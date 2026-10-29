"""Проверка подписи Telegram Mini App. Нельзя доверять initDataUnsafe."""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl
from fastapi import HTTPException

MAX_AUTH_AGE = 3600  # Подпись не должна быть старше часа


def verify_init_data(init_data: str) -> dict:
    """Возвращает проверенный объект Telegram user либо HTTP 401."""
    token = os.getenv("BOT_TOKEN", "")
    if not token or not init_data or len(init_data) > 16384:
        raise HTTPException(status_code=401, detail="Данные входа отсутствуют")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        # Дубликаты параметров недопустимы: неоднозначность вредна для подписи
        if len(pairs) != len(data):
            raise ValueError("Повторяющиеся поля")
        actual_hash = data.pop("hash")
        timestamp = int(data["auth_date"])
        age = time.time() - timestamp
        if age < -60 or age > MAX_AUTH_AGE:
            raise ValueError("Устаревшие данные")
        if len(actual_hash) != 64:
            raise ValueError("Неверная подпись")
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Неверные или устаревшие данные Telegram")

    # По документации Telegram: HMAC от строки отсортированных key=value
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, actual_hash):
        raise HTTPException(status_code=401, detail="Подпись Telegram не совпадает")

    try:
        user = json.loads(data["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            raise ValueError("Пользователь не указан")
        return user
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Не удалось прочитать профиль Telegram")
