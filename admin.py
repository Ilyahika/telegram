"""Full Viva fishing control panel: authenticated, audited administration."""
from typing import Literal
import asyncio
import json
import math
import logging
import os
import platform
import shutil
import sqlite3
import time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
import botapp
from auth import admin_user
from db import session
from config import DB_PATH,STARTED,ADMIN_ID,BOT_TOKEN,WEBAPP_URL,VERSION
from system_state import maintenance_state,set_maintenance,DEFAULT_MESSAGE
from fishing import ensure_fishing,snapshot,GEAR_BY_ID,FISH_BY_ID,FINDS_BY_ID,CASE_BY_ID,effective_cases,level_info
router=APIRouter(prefix='/api/admin')
log=logging.getLogger('miniapp.admin')
# Функция audit: см. параметры, описание и вызовы ниже.
def audit(db, admin_id: int, target, action: str, value: str = '') -> None:
    """Записывает действие администратора в журнал (admin_log)."""
    db.execute('INSERT INTO admin_log (ts, admin_id, target, action, value) VALUES (?,?,?,?,?)',
               (int(time.time()), admin_id, target, action, value[:200]))


# Функция stats: см. параметры, описание и вызовы ниже.
@router.get('/stats')
def stats(deep: bool = False, admin: dict = Depends(admin_user)):
    """
    Сводка: счётчики, проверки системы, информация о сервере.
    deep=true запускает полную проверку целостности БД (PRAGMA quick_check) — это долго на большой базе,
    поэтому по умолчанию она не выполняется.
    """
    now = int(time.time())
    with session(write=True) as db:   # write нужен для проверки записи; транзакция короткая
        # --- тест записи/чтения/удаления: измеряем задержку базы
        t0 = time.perf_counter()
        db.execute("INSERT OR REPLACE INTO db_probe VALUES ('p','ok')")
        probe_ok = db.execute("SELECT value FROM db_probe WHERE id='p'").fetchone()[0] == 'ok'
        db.execute("DELETE FROM db_probe WHERE id='p'")
        ms = round((time.perf_counter() - t0) * 1000, 1)

        # --- все счётчики за 3 запроса (админ с бесконечным балансом в суммы не входит)
        pl = db.execute('''SELECT COUNT(*) AS players,
                                  COALESCE(SUM(CASE WHEN telegram_id != ? THEN coins END), 0) AS coins_total,
                                  COALESCE(SUM(games_played), 0) AS games_played, COALESCE(SUM(games_won), 0) AS games_won,
                                  COALESCE(SUM(created_at > ?), 0) AS new_24h FROM players''', (ADMIN_ID, now - 86400)).fetchone()
        bh = db.execute('''SELECT COALESCE(SUM(blocked = 1), 0) AS blocked, COALESCE(SUM(telegram_id != ? AND last_seen > ?), 0) AS online_now,
                                  COALESCE(SUM(last_seen > ?), 0) AS online_15m,
                                  COALESCE(SUM(last_seen > ?), 0) AS active_24h,
                                  COALESCE(SUM(CASE WHEN telegram_id != ? THEN gems END), 0) AS gems_total,
                                  COALESCE(SUM(taps), 0) AS taps FROM bh''', (ADMIN_ID, now - 75, now - 900, now - 86400, ADMIN_ID)).fetchone()
        levels={}
        for r in db.execute('SELECT COALESCE(f.xp,0),COUNT(*) FROM players p LEFT JOIN fishing_progress f USING(telegram_id) GROUP BY COALESCE(f.xp,0)'):
            lv=str(level_info(r[0])['level']); levels[lv]=levels.get(lv,0)+r[1]
        rows = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                for t in ('players','fishing_progress','fishing_fish','fishing_finds','fishing_gear','fishing_cases','fishing_sessions','fishing_case_settings','admin_log')}   # имена таблиц — из белого списка
        fishing_stats = {
            'fishing_catches': db.execute('SELECT COALESCE(SUM(catches),0) FROM fishing_progress').fetchone()[0],
            'fish_in_bags': db.execute('SELECT COALESCE(SUM(amount),0) FROM fishing_fish').fetchone()[0],
            'finds_in_bags': db.execute('SELECT COALESCE(SUM(amount),0) FROM fishing_finds').fetchone()[0],
            'cases_opened': db.execute('SELECT COALESCE(SUM(opened),0) FROM fishing_cases').fetchone()[0],
        }
        integrity = db.execute('PRAGMA quick_check').fetchone()[0] if deep else None
    st = {**dict(pl), **dict(bh), 'levels': levels, **fishing_stats}

    size_kb = round((os.path.getsize(DB_PATH) if DB_PATH.exists() else 0) / 1024, 1)
    free_mb = shutil.disk_usage(str(DB_PATH.parent)).free // 2 ** 20
    up = int(now - STARTED)
    bot = botapp.state

    def check(name, status, detail):
        return {'n': name, 's': status, 'd': detail}

    checks = [
        check('Авторизация Telegram', 'ok', 'initData подтверждена, ты — админ'),
        check('BOT_TOKEN', 'ok' if BOT_TOKEN else 'fail', ('id бота ' + BOT_TOKEN.split(':')[0]) if BOT_TOKEN else 'не задан'),
        check('Бот (getMe)', 'ok' if bot.username else 'fail', '@' + bot.username if bot.username else (bot.error or 'ещё не ответил')),
        check('Polling бота', 'ok' if bot.polling else 'warn', 'работает' if bot.polling else (bot.error or 'не запущен')),
        check('WEBAPP_URL', 'ok' if WEBAPP_URL.startswith('https://') else 'fail', WEBAPP_URL or 'не задан'),
        check('SQLite запись/чтение', 'ok' if probe_ok else 'fail', f'{ms} мс'),
        check('Технические работы', 'warn' if maintenance_state()['enabled'] else 'ok',
              'включены' if maintenance_state()['enabled'] else 'игра открыта'),
        check('Целостность БД', ('ok' if integrity == 'ok' else 'fail') if deep else 'skip',
              integrity if deep else 'не запускалась — нажми «Глубокая проверка»'),
        check('Файл БД', 'ok' if DB_PATH.exists() else 'fail', f'{size_kb} КБ'),
        check('Свободно на диске', 'ok' if free_mb > 200 else 'warn', f'{free_mb} МБ'),
        check('Время работы', 'ok' if up > 120 else 'warn',
              f'{up // 3600} ч {up // 60 % 60} мин' + (' (недавний рестарт: на Render Free база могла сброситься)' if up < 120 else '')),
    ]
    info = {'Python': platform.python_version(), 'SQLite': sqlite3.sqlite_version, 'Версия': VERSION,
            'Сервер (UTC)': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()), 'Путь БД': str(DB_PATH), 'ADMIN_ID': ADMIN_ID}
    return {'stats':st,'checks':checks,'info':info,'rows':rows,'db_ms':ms,'maintenance':maintenance_state()}

SORTS = {'last_seen': 'b.last_seen', 'coins': 'p.coins', 'xp':'COALESCE(f.xp,0)', 'catches':'COALESCE(f.catches,0)',
         'created_at': 'p.created_at', 'earned': 'p.coins'}


# Функция _like: см. параметры, описание и вызовы ниже.
def _like(q: str) -> str:
    """Экранирует служебные символы LIKE (% _ \\), чтобы поиск был буквальным."""
    return '%' + q.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


# Функция players: см. параметры, описание и вызовы ниже.
@router.get('/players')
def players(q: str = '', flt: str = 'all', sort: str = 'last_seen', offset: int = 0, limit: int = 25,
            admin: dict = Depends(admin_user)):
    """Список игроков: поиск по ID/имени/нику, фильтр all|online|blocked|new, сортировка, постраничный вывод."""
    now, q = int(time.time()), q.strip()
    limit, offset = min(max(limit, 1), 100), max(offset, 0)
    where, args = ['1=1'], []
    if flt == 'online':
        where.append('b.last_seen > ?'); args.append(now - 900)
    elif flt == 'live':
        where.append('b.last_seen > ?'); args.append(now - 75)
    elif flt == 'blocked':
        where.append('b.blocked = 1')
    elif flt == 'new':
        where.append('p.created_at > ?'); args.append(now - 86400)
    if q:
        where.append("(CAST(p.telegram_id AS TEXT) LIKE ? ESCAPE '\\' OR PYLOWER(p.telegram_name) LIKE ? ESCAPE '\\' "
                     "OR PYLOWER(IFNULL(p.nickname,'')) LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    cond = ' AND '.join(where)
    order = SORTS.get(sort, SORTS['last_seen'])
    with session() as db:
        total = db.execute(f'SELECT COUNT(*) FROM players p LEFT JOIN bh b ON b.telegram_id=p.telegram_id LEFT JOIN fishing_progress f ON f.telegram_id=p.telegram_id WHERE {cond}', args).fetchone()[0]
        rows = db.execute(f'''SELECT p.telegram_id, p.telegram_name, p.nickname, p.coins, p.games_played, p.games_won, p.created_at,
                                     b.blocked, b.reason, b.last_seen, b.avatar, COALESCE(f.xp,0) xp, COALESCE(f.catches,0) catches
                              FROM players p LEFT JOIN bh b ON b.telegram_id = p.telegram_id LEFT JOIN fishing_progress f ON f.telegram_id=p.telegram_id
                              WHERE {cond} ORDER BY {order} DESC, p.telegram_id LIMIT ? OFFSET ?''', (*args, limit, offset)).fetchall()
    return {'players': [{**dict(r), 'level':level_info(r['xp'])['level']} for r in rows], 'total': total, 'admin_id': ADMIN_ID}


# Функция player: см. параметры, описание и вызовы ниже.
@router.get('/players/{uid}')
def player(uid:int,admin=Depends(admin_user)):
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Игрок не найден')
        ensure_fishing(db,uid);return snapshot(db,uid)
# Класс Change: см. параметры, описание и вызовы ниже.
class Change(BaseModel):
    kind:str
    key:str=''
    delta:int=Field(default=0,ge=-1000000000,le=1000000000)
    reason:str=Field(default='',max_length=300)
# Функция change: см. параметры, описание и вызовы ниже.
@router.post('/players/{uid}')
def change(uid:int,data:Change,admin=Depends(admin_user)):
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Игрок не найден')
        ensure_fishing(db,uid)
        if data.kind in ['coins','xp']:
            table='players' if data.kind=='coins' else 'fishing_progress'
            db.execute(f'UPDATE {table} SET {data.kind}=MAX(0,{data.kind}+?) WHERE telegram_id=?',(data.delta,uid))
        elif data.kind in ['coins_set','xp_set']:
            key=data.kind[:-4];table='players' if key=='coins' else 'fishing_progress'
            db.execute(f'UPDATE {table} SET {key}=MAX(0,?) WHERE telegram_id=?',(data.delta,uid))
        elif data.kind=='block':
            if uid==ADMIN_ID and data.delta>0: raise HTTPException(400,'Нельзя заблокировать администратора')
            db.execute('UPDATE bh SET blocked=?,reason=? WHERE telegram_id=?',(int(data.delta>0),data.reason,uid))
        elif data.kind=='cooldown':
            db.execute('UPDATE fishing_progress SET last_cast=0 WHERE telegram_id=?',(uid,))
            db.execute('DELETE FROM fishing_attempts WHERE telegram_id=?',(uid,))
        elif data.kind in ['gear','fish','find','case']:
            cat,table,col={'gear':(GEAR_BY_ID,'fishing_gear','gear_key'),'fish':(FISH_BY_ID,'fishing_fish','item_key'),'find':(FINDS_BY_ID,'fishing_finds','item_key'),'case':(CASE_BY_ID,'fishing_cases','case_key')}[data.kind]
            if data.key not in cat:raise HTTPException(400,'Неизвестный предмет')
            db.execute(f'INSERT INTO {table} (telegram_id,{col},amount) VALUES (?,?,?) ON CONFLICT(telegram_id,{col}) DO UPDATE SET amount=MAX(0,amount+?)',(uid,data.key,max(0,data.delta),data.delta))
            if data.kind=='gear':
                g=cat[data.key];slot='tackle' if g['type']=='bait' else g['type']
                amount=db.execute(f'SELECT amount FROM {table} WHERE telegram_id=? AND {col}=?',(uid,data.key)).fetchone()[0]
                if amount==0:
                    remaining=[r[0] for r in db.execute('SELECT gear_key FROM fishing_gear WHERE telegram_id=? AND amount>0',(uid,))]
                    fallback=next((k for k in remaining if k in GEAR_BY_ID and GEAR_BY_ID[k]['type']==g['type']),'')
                    db.execute(f'UPDATE fishing_progress SET {slot}=? WHERE telegram_id=? AND {slot}=?',(fallback,uid,data.key))
        else:raise HTTPException(400,'Неизвестное действие')
        if data.kind=='fish':
            f=FISH_BY_ID[data.key]
            if data.delta>0:
                if data.delta>1000:raise HTTPException(400,'До 1000 рыб за раз')
                db.executemany("INSERT INTO catches_v11(telegram_id,fish_key,kg) VALUES (?,?,?)",[(uid,data.key,f['min_kg'])]*data.delta)
            elif data.delta<0:
                db.execute("DELETE FROM catches_v11 WHERE id IN (SELECT id FROM catches_v11 WHERE telegram_id=? AND fish_key=? AND place='bag' LIMIT ?)",(uid,data.key,-data.delta))
        db.execute('INSERT INTO notices_v11(telegram_id,text,kind) VALUES (?,?,?)',(uid,'Администратор изменил: '+data.kind+' '+str(data.delta),'moderator'))
        db.execute('INSERT INTO admin_log(ts,admin_id,target,action,value) VALUES (?,?,?,?,?)',(int(time.time()),admin['id'],uid,data.kind,f'{data.key}: {data.delta}; {data.reason}'))
        return snapshot(db,uid)

# Функция player_card: см. параметры, описание и вызовы ниже.
@router.get('/player')
def player_card(id:int,admin=Depends(admin_user)):
    state=player(id,admin)
    return {**state['player'], 'fishing':state, 'is_admin':id==ADMIN_ID}

# Класс Act: см. параметры, описание и вызовы ниже.
class Act(BaseModel):
    telegram_id:int
    act:str
    value:str=''

# Функция act: см. параметры, описание и вызовы ниже.
@router.post('/act')
def act(data:Act,admin=Depends(admin_user)):
    mapping={'coins_add':'coins','coins_set':'coins_set','xp_add':'xp','xp_set':'xp_set','block':'block','unblock':'block','cooldown':'cooldown'}
    if data.act in mapping:
        try: amount=1 if data.act=='block' else 0 if data.act in ['unblock','cooldown'] else int(data.value)
        except ValueError:raise HTTPException(400,'Введи целое число')
        if abs(amount)>1000000000:raise HTTPException(400,'Слишком большое значение')
        return change(data.telegram_id,Change(kind=mapping[data.act],delta=amount,reason=data.value if data.act=='block' else ''),admin)
    if data.act not in ['reset','clear_bag','end_cast']:raise HTTPException(400,'Неизвестное действие')
    uid=data.telegram_id
    if uid==ADMIN_ID and data.act=='reset':raise HTTPException(400,'Нельзя сбросить администратора')
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Игрок не найден')
        tables={'clear_bag':['fishing_fish','fishing_finds','catches_v11'],'end_cast':['fishing_sessions'],'reset':['catches_v11','tanks_v11','fishing_migrations','fishing_progress','fishing_fish','fishing_finds','fishing_gear','fishing_cases','fishing_discovered','fishing_sessions','fishing_catch_history','viva_location_records','fishing_buffs','fishing_attempts','fishing_reward_claims']}[data.act]
        for table in tables:db.execute(f'DELETE FROM {table} WHERE telegram_id=?',(uid,))
        if data.act=='reset':db.execute('UPDATE players SET coins=0,nickname=NULL WHERE telegram_id=?',(uid,));ensure_fishing(db,uid)
        audit(db,admin['id'],uid,data.act)
    return {'ok':True}

# Класс CaseSettings: см. параметры, описание и вызовы ниже.
class CaseSettings(BaseModel):
    price:int=Field(ge=0,le=1000000000)
    enabled:bool=True
    weights:dict[str,float]

# Функция cases: см. параметры, описание и вызовы ниже.
@router.get('/cases')
def cases(admin=Depends(admin_user)):
    with session() as db:return {'cases':effective_cases(db),'gear':list(GEAR_BY_ID.values())}

# Функция save_case: см. параметры, описание и вызовы ниже.
@router.post('/cases/{key}')
def save_case(key:str,data:CaseSettings,admin=Depends(admin_user)):
    if key not in CASE_BY_ID:raise HTTPException(404,'Кейс не найден')
    if any(k not in GEAR_BY_ID or GEAR_BY_ID.get(k,{}).get('type')!=CASE_BY_ID[key]['type'] or not math.isfinite(w) or w<0 or w>1000000 for k,w in data.weights.items()):raise HTTPException(400,'Некорректные веса наград')
    valid={k:w for k,w in data.weights.items() if w>0}
    if not valid:raise HTTPException(400,'Нужна хотя бы одна награда с весом больше нуля')
    config=dict(price=data.price,enabled=data.enabled,items=list(valid),weights=list(valid.values()))
    with session(write=True) as db:
        db.execute('INSERT INTO fishing_case_settings VALUES (?,?,?,?) ON CONFLICT(case_key) DO UPDATE SET config=excluded.config,updated_at=excluded.updated_at,updated_by=excluded.updated_by',(key,json.dumps(config),int(time.time()),admin['id']))
        audit(db,admin['id'],None,'case_settings',key+': '+json.dumps(config))
    return {'ok':True}

# Класс Msg: см. параметры, описание и вызовы ниже.
class Msg(BaseModel):
    telegram_id: int
    text: str = Field(min_length=1, max_length=1000)


# Функция message: см. параметры, описание и вызовы ниже.
@router.post('/message')
async def message(data: Msg, admin: dict = Depends(admin_user)):
    """Личное сообщение игроку от имени бота."""
    bot = botapp.state.bot
    if bot is None:
        raise HTTPException(503, 'Бот не запущен')
    try:
        await bot.send_message(data.telegram_id, data.text)
    except Exception as exc:
        raise HTTPException(400, f'Не удалось отправить: {type(exc).__name__}')
    await run_in_threadpool(_audit_once, admin['id'], data.telegram_id, 'message', data.text)
    return {'ok': True}


# Функция _audit_once: см. параметры, описание и вызовы ниже.
def _audit_once(admin_id, target, action, value=''):
    with session(write=True) as db:
        audit(db, admin_id, target, action, value)


# Состояние текущей рассылки (одна за раз)
BROADCAST = {'running': False, 'total': 0, 'sent': 0, 'failed': 0, 'task': None}


# Функция _broadcast_worker: см. параметры, описание и вызовы ниже.
async def _broadcast_worker(bot, ids, text):
    """Фоновая рассылка. Пауза 50 мс между сообщениями — безопасно для лимитов Telegram (~30 сообщ./с)."""
    from aiogram.exceptions import TelegramRetryAfter
    try:
        for uid in ids:
            try:
                await bot.send_message(uid, text)
                BROADCAST['sent'] += 1
            except TelegramRetryAfter as exc:        # Telegram просит подождать
                await asyncio.sleep(exc.retry_after)
                try:
                    await bot.send_message(uid, text)
                    BROADCAST['sent'] += 1
                except Exception:
                    BROADCAST['failed'] += 1
            except Exception:                        # игрок заблокировал бота и т.п.
                BROADCAST['failed'] += 1
            await asyncio.sleep(0.05)
    finally:
        BROADCAST['running'] = False


# Класс Broadcast: см. параметры, описание и вызовы ниже.
class Broadcast(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


# Функция _recipient_ids: см. параметры, описание и вызовы ниже.
def _recipient_ids():
    with session() as db:
        return [r[0] for r in db.execute('SELECT p.telegram_id FROM players p JOIN bh b ON b.telegram_id=p.telegram_id WHERE b.blocked=0')]


# Функция broadcast: см. параметры, описание и вызовы ниже.
@router.post('/broadcast')
async def broadcast(data: Broadcast, admin: dict = Depends(admin_user)):
    """Запускает рассылку всем не заблокированным игрокам."""
    bot = botapp.state.bot
    if bot is None:
        raise HTTPException(503, 'Бот не запущен')
    if BROADCAST['running']:
        raise HTTPException(409, 'Рассылка уже идёт')
    ids = await run_in_threadpool(_recipient_ids)
    BROADCAST.update(running=True, total=len(ids), sent=0, failed=0)
    BROADCAST['task'] = asyncio.create_task(_broadcast_worker(bot, ids, data.text))   # ссылка в словаре — чтобы задачу не удалил сборщик мусора
    await run_in_threadpool(_audit_once, admin['id'], None, 'broadcast', f'{len(ids)} чел.: {data.text}')
    return {'ok': True, 'total': len(ids)}


# Функция broadcast_status: см. параметры, описание и вызовы ниже.
@router.get('/broadcast')
def broadcast_status(admin: dict = Depends(admin_user)):
    """Ход текущей/последней рассылки."""
    return {k: BROADCAST[k] for k in ('running', 'total', 'sent', 'failed')}


# =============================================================================== ЖУРНАЛ
@router.get('/log')
def admin_log(limit: int = 50, admin: dict = Depends(admin_user)):
    """Последние действия администратора."""
    with session() as db:
        rows = db.execute('SELECT ts, admin_id, target, action, value FROM admin_log ORDER BY id DESC LIMIT ?',
                          (min(max(limit, 1), 200),)).fetchall()
    return {'log': [dict(r) for r in rows]}


# ============================================================================= MAINTENANCE / ONLINE
@router.get('/maintenance')
def maintenance(admin: dict = Depends(admin_user)):
    return maintenance_state()


# Класс MaintenanceChange: см. параметры, описание и вызовы ниже.
class MaintenanceChange(BaseModel):
    enabled: bool
    message: str = Field(default=DEFAULT_MESSAGE, max_length=500)


# Функция maintenance_change: см. параметры, описание и вызовы ниже.
@router.post('/maintenance')
def maintenance_change(data: MaintenanceChange, admin: dict = Depends(admin_user)):
    return set_maintenance(data.enabled, data.message, admin['id'])


# Функция live_players: см. параметры, описание и вызовы ниже.
@router.get('/live')
def live_players(admin=Depends(admin_user)):
    now=int(time.time())
    with session() as db:
        rows=db.execute('SELECT p.telegram_id,p.telegram_name,p.nickname,p.coins,b.avatar,b.last_seen,b.blocked,COALESCE(f.xp,0) xp FROM players p JOIN bh b USING(telegram_id) LEFT JOIN fishing_progress f USING(telegram_id) WHERE b.last_seen>=? AND p.telegram_id!=? ORDER BY b.last_seen DESC LIMIT 100',(now-75,ADMIN_ID)).fetchall()
        count=db.execute('SELECT COUNT(*) FROM players p JOIN bh b USING(telegram_id) WHERE b.last_seen>=? AND p.telegram_id!=?',(now-75,ADMIN_ID)).fetchone()[0]
        active=db.execute('SELECT COUNT(*) FROM fishing_sessions WHERE finished=0',()).fetchone()[0]
    return dict(online=[{**dict(r),'level':level_info(r['xp'])['level']} for r in rows],count=count,active_casts=active,updated_at=now,definition='Подписанная активность за последние 75 секунд')

# Класс LuckGrant: см. параметры, описание и вызовы ниже.
class LuckGrant(BaseModel):
    multiplier:Literal[1,2,3,5]
    minutes:int=Field(default=30,ge=1,le=43200)

# Функция grant_luck: см. параметры, описание и вызовы ниже.
@router.post('/players/{uid}/luck')
def grant_luck(uid:int,data:LuckGrant,admin=Depends(admin_user)):
    expires=time.time()+data.minutes*60 if data.multiplier>1 else 0
    with session(write=True) as db:
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(uid,)).fetchone():raise HTTPException(404,'Игрок не найден')
        db.execute('INSERT INTO notices_v11(telegram_id,text,kind) VALUES (?,?,?)',(uid,f'Администратор установил удачу ×{data.multiplier}','moderator'))
        db.execute('INSERT INTO fishing_buffs VALUES (?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET multiplier=excluded.multiplier,expires_at=excluded.expires_at',(uid,data.multiplier,expires))
        audit(db,admin['id'],uid,'luck',f'x{data.multiplier}, {data.minutes} мин., до {int(expires)}')
    return player_card(uid,admin)
