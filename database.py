import sqlite3
DB_NAME = 'database.db'
connection = sqlite3.connect('database.db')
cursor = connection.cursor
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    money INTEGER DEFAULT 1000,
    level INTEGER DEFAULT 1
)
""")
connection.commit()
connection.close()

def get_connection():
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    return connection

def init_database():
    connection = get_connection()
    try:
        connection.execute("""

            CREATE TABLE IF NOT EXISTS players (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                coins INTEGER NOT NULL DEFAULT 100,
                level INTEGER NOT NULL DEFAULT 1

""")
        connection.commit()
    finally:
        connection.close()

def register_user(user_id, username):
    connection = get_connection()

    try:
        connection.execute("""
            INSERT OR IGNORE INTO players
            (telegram_id, username)
            VALUES (?, ?)
        """, (user_id, username))

        # Обновляем имя существующего игрока
        connection.execute("""
            UPDATE players
            SET username = ?
            WHERE telegram_id = ?
        """, (username, user_id))

        connection.commit()

        # Загружаем профиль
        player = connection.execute("""
            SELECT telegram_id, username, coins, level
            FROM players
            WHERE telegram_id = ?
        """, (user_id,)).fetchone()

        return dict(player)

    finally:
        connection.close()





print("База данных подключена")
