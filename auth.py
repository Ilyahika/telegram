"""
auth.py — проверка подписи Telegram Mini App (initData) и зависимости FastAPI для защиты маршрутов.
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Request

import botapp
from config import ADMIN_ID, BOT_TOKEN, INIT_DATA_MAX_AGE, LAST_SEEN_EVERY
from db import session

log = logging.getLogger('miniapp.auth')


# Класс AuthError: см. параметры, описание и вызовы ниже.
class AuthError(Exception):
    """Ошибка проверки initData; code — короткая причина для логов и сообщения пользователю."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# Функция _calc_hash: см. параметры, описание и вызовы ниже.
def _calc_hash(params: dict, secret: bytes) -> str:
    """HMAC-SHA256 от строки «ключ=значение», отсортированной по ключам и склеенной через \\n."""
    data_check = '\n'.join(f'{k}={v}' for k, v in sorted(params.items()))
    return hmac.new(secret, data_check.encode('utf-8'), hashlib.sha256).hexdigest()


# Функция verify_init_data: см. параметры, описание и вызовы ниже.
def verify_init_data(init_data: str, token: str, max_age: int = INIT_DATA_MAX_AGE) -> dict:
    """
    Проверяет подпись Mini App и возвращает {'id', 'first_name', 'username'}.

    По документации Telegram из проверки исключается только поле hash. На всякий случай пробуем
    ещё и вариант без signature — подделать любой из них без токена бота невозможно.
    """
    if not init_data:
        raise AuthError('no_init_data')
    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        raise AuthError('malformed')
    received_hash = params.pop('hash', None)
    if not received_hash:
        raise AuthError('no_hash')

    secret = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()  # ключ из токена бота
    variants = [params]
    if 'signature' in params:
        variants.append({k: v for k, v in params.items() if k != 'signature'})
    received = received_hash.strip().lower().encode('utf-8')
    if not any(hmac.compare_digest(_calc_hash(v, secret).encode('utf-8'), received) for v in variants):
        raise AuthError('bad_hash')

    try:
        auth_date = int(params['auth_date'])
    except (KeyError, ValueError):
        raise AuthError('bad_auth_date')
    now = int(time.time())
    if auth_date > now + 300 or now - auth_date > max_age:   # из будущего или протухла
        raise AuthError('expired')

    try:
        user = json.loads(params['user'])
        user_id = int(user['id'])
    except (KeyError, ValueError, TypeError):
        raise AuthError('no_user')
    if user_id <= 0:
        raise AuthError('no_user')
    return {'id': user_id,
            'first_name': str(user.get('first_name') or 'Игрок')[:100],
            'username': str(user.get('username') or '')[:100]}


# Функция register: см. параметры, описание и вызовы ниже.
def register(user: dict) -> None:
    """
    Регистрирует игрока при первом входе, обновляет имя и «был онлайн», проверяет блокировку.

    Обычный случай — только ЧТЕНИЕ. Запись в БД происходит лишь для нового игрока, при смене имени
    или если last_seen старше LAST_SEEN_EVERY секунд.
    """
    uid, now = user['id'], int(time.time())
    with session() as db:
        row = db.execute('''SELECT p.telegram_name, b.blocked, b.reason, b.last_seen
                            FROM players p JOIN bh b ON b.telegram_id = p.telegram_id
                            WHERE p.telegram_id=?''', (uid,)).fetchone()
    if row is None or row['telegram_name'] != user['first_name'] or now - row['last_seen'] >= LAST_SEEN_EVERY:
        with session(write=True) as db:
            db.execute('INSERT OR IGNORE INTO players (telegram_id, telegram_name, created_at) VALUES (?,?,?)',
                       (uid, user['first_name'], now))
            db.execute('INSERT OR IGNORE INTO bh (telegram_id, last_claim, energy_ts) VALUES (?,?,?)',
                       (uid, now, now))
            db.execute('UPDATE players SET telegram_name=? WHERE telegram_id=?', (user['first_name'], uid))
            db.execute('UPDATE bh SET last_seen=? WHERE telegram_id=?', (now, uid))
            row = db.execute('SELECT blocked, reason FROM bh WHERE telegram_id=?', (uid,)).fetchone()
    if row['blocked'] and uid != ADMIN_ID:
        raise HTTPException(403, 'Аккаунт заблокирован' + (f": {row['reason']}" if row['reason'] else ''))


# Функция signed_user: см. параметры, описание и вызовы ниже.
def signed_user(request: Request) -> dict:
    """Only Telegram HMAC authentication. Called by the maintenance status endpoint too."""
    if not BOT_TOKEN:
        raise HTTPException(503, 'BOT_TOKEN не настроен на сервере')
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    try:
        return verify_init_data(init_data, BOT_TOKEN)
    except AuthError as exc:
        log.warning('Авторизация Telegram не прошла: %s (длина initData=%d)', exc.code, len(init_data))
        messages = {
            'no_init_data': 'Открой Mini App кнопкой «Открыть» внутри Telegram, а не в браузере.',
            'expired': 'Данные Telegram устарели. Закрой Mini App и открой заново.',
            'bad_hash': (f'Не удалось подтвердить профиль (bad_hash). Открой Mini App из чата с ботом '
                         f'@{botapp.state.username or "?"} и проверь BOT_TOKEN.'),
        }
        raise HTTPException(401, messages.get(exc.code, f'Не удалось подтвердить профиль Telegram ({exc.code}).'))


# Функция current_user: см. параметры, описание и вызовы ниже.
def current_user(request: Request) -> dict:
    """Blocks every ordinary gameplay API during maintenance; admins bypass entirely."""
    user = signed_user(request)
    if user['id'] != ADMIN_ID:
        from system_state import maintenance_state
        state = maintenance_state()
        if state['enabled']:
            raise HTTPException(503, detail={'code': 'MAINTENANCE', 'message': state['message']})
    register(user)
    return user


# Функция admin_user: см. параметры, описание и вызовы ниже.
def admin_user(user: dict = Depends(current_user)) -> dict:
    """Зависимость FastAPI: пускает только администратора (ADMIN_ID)."""
    if user['id'] != ADMIN_ID:
        raise HTTPException(403, 'Нет доступа')
    return user
