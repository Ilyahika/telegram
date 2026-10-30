"""Persisted reward claims, fishing allowance and public chat."""
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel,Field
from auth import current_user,admin_user
from db import session
router=APIRouter(prefix='/api/community')

# Функция attempt_state: см. параметры, описание и вызовы ниже.
def attempt_state(db,uid):
    now=int(time.time());r=db.execute('SELECT * FROM fishing_attempts WHERE telegram_id=?',(uid,)).fetchone()
    restored=max(0,(now-r['window_start'])//60) if r else 0
    missing=max(0,min(5,r['used'])-restored) if r else 0
    next_at=r['window_start']+(restored+1)*60 if missing else 0
    return dict(limit=5,remaining=5-missing,next_at=next_at,resets_at=next_at,period_seconds=60)

# Функция spend_attempt: см. параметры, описание и вызовы ниже.
def spend_attempt(db,uid):
    now=int(time.time());state=attempt_state(db,uid)
    if state['remaining']<=0:raise HTTPException(429,'Нет попыток. Одна попытка восстанавливается каждую минуту.')
    # Preserve partial-minute progress while the bank is below capacity.
    anchor=now if state['remaining']==5 else state['next_at']-60
    used=6-state['remaining']
    db.execute('INSERT INTO fishing_attempts VALUES (?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET window_start=excluded.window_start,used=excluded.used',(uid,anchor,used))

# Функция reward_state: см. параметры, описание и вызовы ниже.
def reward_state(db,uid):
    r=db.execute('SELECT * FROM fishing_reward_claims WHERE telegram_id=?',(uid,)).fetchone();now=int(time.time())
    return dict(hourly_at=r['hourly_at'] if r else 0,daily_at=r['daily_at'] if r else 0,hourly_ready=not r or now-r['hourly_at']>=3600,daily_ready=not r or now-r['daily_at']>=86400,streak=r['streak'] if r else 0,server_time=now)

# Функция rewards: см. параметры, описание и вызовы ниже.
@router.get('/rewards')
def rewards(user=Depends(current_user)):
    with session() as db:return reward_state(db,user['id'])
# Класс Claim: см. параметры, описание и вызовы ниже.
class Claim(BaseModel):
    kind:Literal['hourly','daily']
# Функция claim: см. параметры, описание и вызовы ниже.
@router.post('/rewards/claim')
def claim(data:Claim,user=Depends(current_user)):
    from fishing import ensure_fishing,snapshot
    uid=user['id'];now=int(time.time())
    with session(write=True) as db:
        ensure_fishing(db,uid);db.execute('INSERT OR IGNORE INTO fishing_reward_claims(telegram_id) VALUES (?)',(uid,))
        r=db.execute('SELECT * FROM fishing_reward_claims WHERE telegram_id=?',(uid,)).fetchone();column=data.kind+'_at';period=3600 if data.kind=='hourly' else 86400
        if now-r[column]<period:raise HTTPException(429,'Награда уже получена. Дождись окончания таймера.')
        streak=r['streak'];coins=100;xp=10
        if data.kind=='daily':
            streak=min(7,streak+1) if r['daily_at'] and now-r['daily_at']<172800 else 1
            coins=500+(streak-1)*100;xp=50
            db.execute("INSERT INTO fishing_cases(telegram_id,case_key,amount) VALUES (?,'shore',1) ON CONFLICT(telegram_id,case_key) DO UPDATE SET amount=amount+1",(uid,))
        db.execute(f'UPDATE fishing_reward_claims SET {column}=?,streak=? WHERE telegram_id=?',(now,streak,uid))
        db.execute('UPDATE players SET coins=coins+? WHERE telegram_id=?',(coins,uid));db.execute('UPDATE fishing_progress SET xp=xp+? WHERE telegram_id=?',(xp,uid))
        return dict(coins=coins,xp=xp,case='shore' if data.kind=='daily' else None,rewards=reward_state(db,uid),state=snapshot(db,uid))

# Класс Message: см. параметры, описание и вызовы ниже.
class Message(BaseModel):
    text:str=Field(min_length=1,max_length=300)
# Функция ensure_chat_bans: см. параметры, описание и вызовы ниже.
@router.get('/chat')
def ensure_chat_bans(db):
    db.execute('CREATE TABLE IF NOT EXISTS viva_chat_bans(uid INTEGER PRIMARY KEY, banned_at INTEGER NOT NULL, admin_id INTEGER NOT NULL)')

# Функция blocked: см. параметры, описание и вызовы ниже.
def blocked(db,uid):
    ensure_chat_bans(db)
    return bool(db.execute('SELECT 1 FROM viva_chat_bans WHERE uid=?',(uid,)).fetchone())

# Функция chat: см. параметры, описание и вызовы ниже.
def chat(user=Depends(current_user)):
    with session() as db:
        is_blocked=blocked(db,user['id'])

        rows=db.execute('SELECT c.id,c.telegram_id,c.text,c.created_at,c.deleted,p.nickname,p.telegram_name,b.avatar FROM fishing_chat c JOIN players p USING(telegram_id) JOIN bh b USING(telegram_id) ORDER BY c.id DESC LIMIT 50').fetchall()
    return {'messages':[dict(r) for r in reversed(rows)],'is_admin':user['id']==__import__('config').ADMIN_ID,'server_time':int(time.time()),'blocked':is_blocked}
# Функция send: см. параметры, описание и вызовы ниже.
@router.post('/chat')
def send(data:Message,user=Depends(current_user)):
    text=data.text.strip();now=int(time.time());uid=user['id']
    if not text or len(text.splitlines())>5 or any(not c.isprintable() and c!='\n' for c in text):raise HTTPException(400,'Сообщение: до 300 символов и 5 строк')
    with session(write=True) as db:
        if blocked(db,uid):raise HTTPException(403,'Администратор ограничил доступ к общему чату')
        last=db.execute('SELECT MAX(created_at) FROM fishing_chat WHERE telegram_id=?',(uid,)).fetchone()[0]
        if last is not None and now-last<5:raise HTTPException(429,'Можно отправлять сообщение раз в 5 секунд')
        db.execute('INSERT INTO fishing_chat(telegram_id,text,created_at) VALUES (?,?,?)',(uid,text,now))
    return {'ok':True}
# Класс DeleteMessage: см. параметры, описание и вызовы ниже.
class DeleteMessage(BaseModel):
    id:int
# Функция delete: см. параметры, описание и вызовы ниже.
@router.post('/chat/delete')
def delete(data:DeleteMessage,admin=Depends(admin_user)):
    with session(write=True) as db:
        target=db.execute('SELECT telegram_id FROM fishing_chat WHERE id=?',(data.id,)).fetchone()
        if not target:raise HTTPException(404,'Сообщение не найдено')
        db.execute("UPDATE fishing_chat SET deleted=1,text='' WHERE id=?",(data.id,))
        db.execute('INSERT INTO admin_log(ts,admin_id,target,action,value) VALUES (?,?,?,?,?)',(int(time.time()),admin['id'],target[0],'chat_delete',str(data.id)))
    return {'ok':True}

# Класс ChatBan: см. параметры, описание и вызовы ниже.
class ChatBan(BaseModel):
    uid:int=Field(gt=0)
    banned:bool

# Функция chat_ban: см. параметры, описание и вызовы ниже.
@router.post('/chat/ban')
def chat_ban(data:ChatBan,admin=Depends(admin_user)):
    with session(write=True) as db:
        ensure_chat_bans(db)
        if data.uid==admin['id']:raise HTTPException(400,'Нельзя заблокировать себя')
        if not db.execute('SELECT 1 FROM players WHERE telegram_id=?',(data.uid,)).fetchone():raise HTTPException(404,'Игрок не найден')
        if data.banned:
            db.execute('INSERT OR REPLACE INTO viva_chat_bans(uid,banned_at,admin_id) VALUES(?,?,?)',(data.uid,int(time.time()),admin['id']))
        else:db.execute('DELETE FROM viva_chat_bans WHERE uid=?',(data.uid,))
        db.execute('INSERT INTO admin_log(ts,admin_id,target,action,value) VALUES(?,?,?,?,?)',(int(time.time()),admin['id'],data.uid,'chat_ban',str(data.banned)))
    return {'ok':True,'banned':data.banned}

# Функция chat_bans: см. параметры, описание и вызовы ниже.
@router.get('/chat/bans')
def chat_bans(admin=Depends(admin_user)):
    with session() as db:
        ensure_chat_bans(db)
        return {'players':[dict(r) for r in db.execute('SELECT uid,banned_at FROM viva_chat_bans ORDER BY banned_at DESC LIMIT 100').fetchall()]}
