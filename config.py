"""
config.py — настройки приложения.

Все значения берутся из переменных окружения (на Render: Environment).
Этот модуль ничего не импортирует из проекта, поэтому циклических импортов не бывает.
"""
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent   # папка, где лежит проект
STARTED = time.time()                    # момент запуска сервера (для аптайма в админке)
VERSION = 'Viva.Beta.V1 (14)'


# Функция _env: см. параметры, описание и вызовы ниже.
def _env(name: str, default: str = '') -> str:
    """Читает переменную окружения и убирает пробелы, переносы строк и случайные кавычки."""
    return os.getenv(name, default).strip().strip('"').strip("'").strip()


BOT_TOKEN = _env('BOT_TOKEN')                          # токен бота от @BotFather
_url = (_env('RENDER_EXTERNAL_URL') or _env('WEBAPP_URL')).rstrip('/')
WEBAPP_URL = _url + '/' if _url else ''                # Render всегда имеет приоритет: кнопка ведёт на тот же сервер, что обслуживает API
ADMIN_ID = 1181838335  # единственный администратор; проверяется на сервере по подписи Telegram
DB_PATH = Path(_env('DB_PATH') or ROOT / 'database.db')  # путь к SQLite (на Render с диском: /var/data/database.db)

INIT_DATA_MAX_AGE = 24 * 3600   # сколько секунд действует подпись initData от Telegram
LAST_SEEN_EVERY = 30            # как часто (сек) обновлять «был онлайн», чтобы не писать в БД на каждый клик

# CORS: авторизация идёт заголовком X-Telegram-Init-Data (подписанным токеном бота), а не cookie,
# поэтому разрешать запросы с любого адреса безопасно. Так страница работает с GitHub Pages, Render и т.д.,
# и не ломается из-за опечатки в WEBAPP_URL.
CORS_ORIGINS = ['*']
