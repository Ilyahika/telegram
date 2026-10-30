"""Maintenance mode persisted in SQLite. The database is the source of truth."""
import time
from db import session

DEFAULT_MESSAGE = 'Мы обновляем игру и улучшаем сервер. Пожалуйста, зайдите немного позже.'


# Функция maintenance_state: см. параметры, описание и вызовы ниже.
def maintenance_state(db=None) -> dict:
    def read(conn):
        row = conn.execute('SELECT enabled, message, updated_at, updated_by FROM site_settings WHERE id=1').fetchone()
        if row is None:
            return {'enabled': False, 'message': DEFAULT_MESSAGE, 'updated_at': 0, 'updated_by': None}
        return {'enabled': bool(row['enabled']), 'message': row['message'],
                'updated_at': row['updated_at'], 'updated_by': row['updated_by']}
    if db is not None:
        return read(db)
    with session() as conn:
        return read(conn)


# Функция set_maintenance: см. параметры, описание и вызовы ниже.
def set_maintenance(enabled: bool, message: str, admin_id: int) -> dict:
    msg = message.strip() or DEFAULT_MESSAGE
    now = int(time.time())
    with session(write=True) as db:
        db.execute('''INSERT INTO site_settings (id, enabled, message, updated_at, updated_by)
                      VALUES (1, ?, ?, ?, ?)
                      ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,
                          message=excluded.message, updated_at=excluded.updated_at,
                          updated_by=excluded.updated_by''', (int(enabled), msg, now, admin_id))
        db.execute('INSERT INTO admin_log (ts, admin_id, target, action, value) VALUES (?,?,?,?,?)',
                   (now, admin_id, None, 'maintenance_on' if enabled else 'maintenance_off', msg[:200]))
    return {'enabled': enabled, 'message': msg, 'updated_at': now, 'updated_by': admin_id}
