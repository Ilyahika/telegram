"""SQLite-хранилище профилей QWE. Для продакшена на Render лучше PostgreSQL."""
import sqlite3
from pathlib import Path

# База хранится рядом с этим файлом. На обычном Render-диске она НЕ постоянная.
DB_PATH = Path(__file__).resolve().parent / "qwe.db"


def connection():
    """Создаём новое соединение для каждой операции (без общих курсоров)."""
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row  # Колонки можно читать по именам
    return db


def initialize():
    """Безопасно создаём таблицу, если она отсутствует."""
    db = connection()
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                telegram_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                username TEXT,
                photo_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.commit()
    finally:
        db.close()


def upsert_player(user: dict) -> dict:
    """Создаём игрока один раз и обновляем публичные данные при новых входах."""
    telegram_id = int(user["id"])
    display_name = str(user.get("first_name") or "Игрок")[:128]
    username = str(user["username"])[:64] if user.get("username") else None
    photo_url = str(user["photo_url"])[:2048] if user.get("photo_url") else None
    db = connection()
    try:
        db.execute("""
            INSERT INTO players (telegram_id, display_name, username, photo_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                display_name = excluded.display_name,
                username = excluded.username,
                photo_url = excluded.photo_url,
                last_seen_at = CURRENT_TIMESTAMP
        """, (telegram_id, display_name, username, photo_url))
        db.commit()
        row = db.execute("""
            SELECT telegram_id, display_name, username, photo_url, created_at
            FROM players WHERE telegram_id = ?
        """, (telegram_id,)).fetchone()
        return dict(row)
    finally:
        db.close()
