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
        # Обновление схемы без удаления старых профилей.
        existing = {row[1] for row in db.execute("PRAGMA table_info(players)")}
        additions = {
            "level": "INTEGER NOT NULL DEFAULT 1",
            "points": "INTEGER NOT NULL DEFAULT 100",
            "bitcoin": "REAL NOT NULL DEFAULT 0",
            "bank_points": "INTEGER NOT NULL DEFAULT 0",
            "bank_rate": "REAL NOT NULL DEFAULT 0",
            "games_played": "INTEGER NOT NULL DEFAULT 0",
            "games_won": "INTEGER NOT NULL DEFAULT 0",
            "games_lost": "INTEGER NOT NULL DEFAULT 0",
            "favorite_game": "TEXT NOT NULL DEFAULT 'Нет'",
            "property_name": "TEXT NOT NULL DEFAULT 'Пока нет'",
            "hourly_claimed_at": "INTEGER NOT NULL DEFAULT 0",
            "daily_claimed_at": "INTEGER NOT NULL DEFAULT 0",
            "rescue_claimed_at": "INTEGER NOT NULL DEFAULT 0"
        }
        for field, definition in additions.items():
            if field not in existing:
                db.execute(f"ALTER TABLE players ADD COLUMN {field} {definition}")
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
            SELECT *
            FROM players WHERE telegram_id = ?
        """, (telegram_id,)).fetchone()
        return dict(row)
    finally:
        db.close()


def claim_bonus(telegram_id: int, kind: str) -> dict:
    """Начисление бесплатных виртуальных очков, время проверяется сервером."""
    import time
    from fastapi import HTTPException
    field, cooldown, amount = {
        "hourly": ("hourly_claimed_at", 3600, 30),
        "daily": ("daily_claimed_at", 86400, 150),
        "rescue": ("rescue_claimed_at", 86400, 100),
    }.get(kind, (None, None, None))
    if not field:
        raise HTTPException(400, "Неизвестная награда")
    db = connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        player = db.execute("SELECT * FROM players WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not player:
            raise HTTPException(404, "Профиль не найден")
        if kind == "rescue" and player["points"] > 0:
            raise HTTPException(400, "Бонус доступен при нулевом балансе")
        now = int(time.time())
        last = player[field]
        if now - last < cooldown:
            raise HTTPException(429, f"Подожди ещё {cooldown-(now-last)} секунд")
        db.execute(f"UPDATE players SET points=points+?, {field}=? WHERE telegram_id=?", (amount, now, telegram_id))
        db.commit()
        return {"awarded": amount, "points": player["points"] + amount}
    finally:
        db.close()
