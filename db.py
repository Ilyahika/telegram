"""
db.py — работа с SQLite: подключение, схема, миграции.

Главные причины прежних «вечных загрузок» были здесь:
  * каждый запрос заново выполнял CREATE TABLE и писал last_seen -> блокировки базы;
  * журнал был в режиме DELETE: пишущий запрос блокировал всех читающих.
Теперь: схема создаётся ОДИН раз при старте, включён режим WAL (читатели не ждут писателя),
а запись в «был онлайн» делается не чаще раза в 30 секунд.
"""
import logging
import sqlite3
from contextlib import contextmanager

from config import DB_PATH

log = logging.getLogger('miniapp.db')

# --------------------------------------------------------------------------- схема
SCHEMA = '''
CREATE TABLE IF NOT EXISTS players (          -- основной профиль игрока
    telegram_id   INTEGER PRIMARY KEY,
    telegram_name TEXT    NOT NULL,
    nickname      TEXT,
    coins         INTEGER NOT NULL DEFAULT 0, -- доллары
    games_played  INTEGER NOT NULL DEFAULT 0,
    games_won     INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bh (               -- данные «дома»: звёзды, уровень, энергия, блокировка
    telegram_id INTEGER PRIMARY KEY,
    gems        INTEGER NOT NULL DEFAULT 0,   -- звёзды
    house       INTEGER NOT NULL DEFAULT 1,   -- уровень дома
    last_claim  INTEGER NOT NULL DEFAULT 0,   -- когда последний раз забирали доход
    blocked     INTEGER NOT NULL DEFAULT 0,
    reason      TEXT,
    last_seen   INTEGER NOT NULL DEFAULT 0,
    energy      REAL    NOT NULL DEFAULT 50,
    energy_ts   INTEGER NOT NULL DEFAULT 0,
    last_daily  INTEGER NOT NULL DEFAULT 0,
    taps        INTEGER NOT NULL DEFAULT 0,
    earned      INTEGER NOT NULL DEFAULT 0,
    avatar      TEXT    NOT NULL DEFAULT '🏠'
);
CREATE TABLE IF NOT EXISTS cars (             -- гараж
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    car         TEXT    NOT NULL,             -- индекс машины в catalog.CARS
    ts          INTEGER NOT NULL,
    parked      INTEGER NOT NULL DEFAULT 0    -- 1 = машина дает бонус к доходу
);
CREATE TABLE IF NOT EXISTS mines2 (           -- текущая игра «Мины» (одна на игрока)
    telegram_id INTEGER PRIMARY KEY,
    bet         INTEGER,
    mines       INTEGER,
    mines_json  TEXT,
    opened_json TEXT,
    status      TEXT,
    created_at  INTEGER
);
CREATE TABLE IF NOT EXISTS admin_log (        -- журнал действий администратора
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    target   INTEGER,
    action   TEXT NOT NULL,
    value    TEXT
);
CREATE TABLE IF NOT EXISTS db_probe (id TEXT PRIMARY KEY, value TEXT NOT NULL);  -- проверка записи в админке
CREATE TABLE IF NOT EXISTS fishing_progress (
    telegram_id INTEGER PRIMARY KEY,
    casts INTEGER NOT NULL DEFAULT 0,
    catches INTEGER NOT NULL DEFAULT 0,
    last_cast INTEGER NOT NULL DEFAULT 0,
    rod TEXT NOT NULL DEFAULT 'starter_rod',
    tackle TEXT NOT NULL DEFAULT 'starter_lure'
);
CREATE TABLE IF NOT EXISTS fishing_fish (
    telegram_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id,item_key)
);
CREATE TABLE IF NOT EXISTS fishing_discovered (
    telegram_id INTEGER NOT NULL,
    fish_key TEXT NOT NULL,
    PRIMARY KEY (telegram_id,fish_key)
);
CREATE TABLE IF NOT EXISTS fishing_finds (
    telegram_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id,item_key)
);
CREATE TABLE IF NOT EXISTS fishing_gear (
    telegram_id INTEGER NOT NULL,
    gear_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id,gear_key)
);
CREATE TABLE IF NOT EXISTS fishing_cases (
    telegram_id INTEGER NOT NULL,
    case_key TEXT NOT NULL,
    opened INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (telegram_id,case_key)
);
CREATE TABLE IF NOT EXISTS fishing_catch_history (id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,fish_key TEXT NOT NULL,kg REAL NOT NULL,ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS viva_location_records (telegram_id INTEGER NOT NULL, location TEXT NOT NULL, fish_key TEXT NOT NULL, rarity TEXT NOT NULL, kg REAL NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY (telegram_id, location));
CREATE TABLE IF NOT EXISTS fishing_attempts (telegram_id INTEGER PRIMARY KEY,window_start INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fishing_reward_claims (telegram_id INTEGER PRIMARY KEY,hourly_at INTEGER NOT NULL DEFAULT 0,daily_at INTEGER NOT NULL DEFAULT 0,streak INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fishing_chat (id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL,text TEXT NOT NULL,created_at INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_chat_owner ON fishing_chat(telegram_id,created_at);
CREATE TABLE IF NOT EXISTS fishing_buffs (telegram_id INTEGER PRIMARY KEY,multiplier INTEGER NOT NULL DEFAULT 1,expires_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fishing_migrations (telegram_id INTEGER NOT NULL,version TEXT NOT NULL,PRIMARY KEY(telegram_id,version));
CREATE TABLE IF NOT EXISTS fishing_case_settings (case_key TEXT PRIMARY KEY, config TEXT NOT NULL, updated_at INTEGER NOT NULL, updated_by INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS fishing_sessions (telegram_id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,payload TEXT NOT NULL,expires REAL NOT NULL,finished INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS site_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    enabled INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER
);
'''

# Индексы создаются после миграций (в старых базах колонок могло не быть)
INDEXES = '''
CREATE INDEX IF NOT EXISTS idx_bh_seen      ON bh(last_seen);
CREATE INDEX IF NOT EXISTS idx_bh_house     ON bh(house, blocked);
CREATE INDEX IF NOT EXISTS idx_players_made ON players(created_at);
CREATE INDEX IF NOT EXISTS idx_players_coin ON players(coins);
CREATE INDEX IF NOT EXISTS idx_cars_owner   ON cars(telegram_id, parked);
CREATE INDEX IF NOT EXISTS idx_log_ts       ON admin_log(ts);
CREATE INDEX IF NOT EXISTS idx_fish_owner ON fishing_fish(telegram_id);
'''

# Колонки, которые могли отсутствовать в базах старых версий
MIGRATIONS = {
    'bh': {
        'energy': 'REAL NOT NULL DEFAULT 50', 'energy_ts': 'INTEGER NOT NULL DEFAULT 0',
        'last_daily': 'INTEGER NOT NULL DEFAULT 0', 'taps': 'INTEGER NOT NULL DEFAULT 0',
        'earned': 'INTEGER NOT NULL DEFAULT 0', "avatar": "TEXT NOT NULL DEFAULT '🏠'",
        'blocked': 'INTEGER NOT NULL DEFAULT 0', 'reason': 'TEXT', 'last_seen': 'INTEGER NOT NULL DEFAULT 0',
    },
    'fishing_cases': {'amount':'INTEGER NOT NULL DEFAULT 0'},
    'fishing_progress': {'rescue_at':'INTEGER NOT NULL DEFAULT 0','xp':'INTEGER NOT NULL DEFAULT 0','reel':"TEXT NOT NULL DEFAULT ''",'line':"TEXT NOT NULL DEFAULT ''",'spoon':"TEXT NOT NULL DEFAULT ''",'spinner':"TEXT NOT NULL DEFAULT ''"},
    'cars': {'parked': 'INTEGER NOT NULL DEFAULT 0'},
}


# Функция _lower: см. параметры, описание и вызовы ниже.
def _lower(value):
    """SQL-функция PYLOWER: регистронезависимый поиск, работает и для кириллицы (встроенный LOWER — только латиница)."""
    return value.lower() if isinstance(value, str) else ''


# Функция _connect: см. параметры, описание и вызовы ниже.
def _connect() -> sqlite3.Connection:
    """Новое соединение с нужными настройками."""
    # isolation_level=None -> автокоммит: транзакциями управляем сами (BEGIN/COMMIT ниже)
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row                  # доступ к колонкам по имени: row['coins']
    conn.execute('PRAGMA busy_timeout=15000')       # ждать освобождения блокировки до 15 с, а не падать сразу
    conn.execute('PRAGMA synchronous=FULL')       # безопасно в режиме WAL и заметно быстрее записи
    conn.create_function('PYLOWER', 1, _lower, deterministic=True)
    return conn


# Функция session: см. параметры, описание и вызовы ниже.
@contextmanager
def session(write: bool = False):
    """
    Соединение с БД на время одного запроса.

    write=False — только чтение (блокировок нет, WAL позволяет читать параллельно с записью).
    write=True  — сразу берём блокировку записи (BEGIN IMMEDIATE): два одновременных клика
                  игрока не смогут «потратить» одни и те же деньги дважды.
    При исключении (в т.ч. HTTPException) транзакция откатывается. Соединение закрывается всегда.
    """
    conn = _connect()
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write:
            conn.execute('COMMIT')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


# Функция init_db: см. параметры, описание и вызовы ниже.
def init_db() -> None:
    """Создаёт таблицы, добавляет недостающие колонки и индексы. Вызывается один раз при старте."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.execute('PRAGMA journal_mode=WAL')     # режим журнала сохраняется в файле БД навсегда
        conn.executescript(SCHEMA)
        from features_v11 import SCHEMA as V11_SCHEMA
        conn.executescript(V11_SCHEMA)
        for table, columns in MIGRATIONS.items():
            have = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            for column, ddl in columns.items():
                if column not in have:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
                    log.info('Миграция: %s.%s добавлена', table, column)
        conn.execute("DELETE FROM cars WHERE car NOT GLOB '[0-9]*'")   # мусор от старых версий
        from v14 import migrate as migrate_v14
        migrate_v14(conn)
        conn.executescript(INDEXES)
    finally:
        conn.close()
    log.info('База готова: %s', DB_PATH)


# Функция checkpoint_db: см. параметры, описание и вызовы ниже.
def checkpoint_db() -> None:
    """Consolidate WAL after graceful shutdown; committed changes already persist with FULL."""
    conn=_connect()
    try:conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:conn.close()
